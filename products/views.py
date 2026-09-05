from decimal import Decimal

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.utils import timezone
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from .models import (
    Product,
    Category,
    CartItem,
    Cart,
    Order,
    OrderItem,
    Wishlist,
    Review,
    UserProfile,
    Coupon,
)

import razorpay
from django.conf import settings


# =========================================================
# RAZORPAY CLIENT
# =========================================================

razorpay_client = razorpay.Client(
    auth=(
        settings.RAZORPAY_KEY_ID,
        settings.RAZORPAY_TEST_KEY_SECRET
    )
)


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def safe_back_url(request, default='/products/'):
    """
    Return a safe local redirect URL.

    Prevents redirecting the user to an external website
    using a manipulated HTTP_REFERER.
    """

    referer = request.META.get('HTTP_REFERER')

    if not referer:
        return default

    try:
        from urllib.parse import urlparse

        parsed = urlparse(referer)

        # Only allow same-host redirects
        if parsed.netloc == request.get_host():
            return referer

    except Exception:
        pass

    return default

def get_login_attempt_key(request, username):
    """
    Create a stable cache key for login attempt tracking.
    Uses both username and client IP.
    """

    import hashlib

    ip_address = request.META.get(
        'REMOTE_ADDR',
        'unknown'
    )

    raw_key = f"{username.lower()}:{ip_address}"

    hashed_key = hashlib.sha256(
        raw_key.encode()
    ).hexdigest()

    return f"login_attempts:{hashed_key}"

def is_login_blocked(request, username):
    """
    Check whether this username/IP combination
    has exceeded the allowed failed login attempts.
    """

    key = get_login_attempt_key(
        request,
        username
    )

    attempts = cache.get(
        key,
        0
    )

    return attempts >= 5

def record_failed_login(request, username):
    """
    Record a failed login attempt.

    5 failed attempts within 15 minutes
    temporarily block further attempts.
    """

    key = get_login_attempt_key(
        request,
        username
    )

    attempts = cache.get(
        key,
        0
    )

    cache.set(
        key,
        attempts + 1,
        60 * 15
    )


def clear_login_attempts(request, username):
    """
    Clear failed login attempts after
    successful authentication.
    """

    key = get_login_attempt_key(
        request,
        username
    )

    cache.delete(key)


def checkout_context(
    cart_items,
    total,
    discount,
    final_total,
    coupon,
    profile,
    error=None
):
    """
    Common checkout context so we don't duplicate
    the same dictionary everywhere.
    """

    context = {
        'cart_items': cart_items,
        'total': total,
        'discount': discount,
        'final_total': final_total,
        'coupon': coupon,
        'profile': profile,
    }

    if error:
        context['error'] = error

    return context


# =========================================================
# CART
# =========================================================

@login_required
@require_POST
def add_to_cart(request, id):

    product = get_object_or_404(
        Product,
        id=id
    )

    # Never add unavailable products
    if product.stock <= 0:

        return redirect(
            safe_back_url(request)
        )

    cart, created = Cart.objects.get_or_create(
        user=request.user
    )

    cart_item = CartItem.objects.filter(
        cart=cart,
        product=product
    ).first()

    if cart_item:

        # Never exceed available stock
        if cart_item.quantity < product.stock:

            cart_item.quantity += 1

            cart_item.save(
                update_fields=['quantity']
            )

    else:

        CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=1
        )

    return redirect(
        safe_back_url(request)
    )


@login_required
def cart(request):

    cart = Cart.objects.get_or_create(
        user=request.user
    )[0]

    cart_items = cart.items.select_related(
        'product'
    )

    total = Decimal('0')

    for item in cart_items:

        item.subtotal = (
            item.product.price
            * item.quantity
        )

        total += item.subtotal

    return render(
        request,
        'products/cart.html',
        {
            'cart_items': cart_items,
            'total': total,
        }
    )


@login_required
@require_POST
def increase_quantity(request, id):

    cart_item = get_object_or_404(
        CartItem,
        id=id,
        cart__user=request.user
    )

    product = cart_item.product

    # Stock limit
    if cart_item.quantity < product.stock:

        cart_item.quantity += 1

        cart_item.save(
            update_fields=['quantity']
        )

    return redirect('cart')


@login_required
@require_POST
def decrease_quantity(request, id):

    cart_item = get_object_or_404(
        CartItem,
        id=id,
        cart__user=request.user
    )

    if cart_item.quantity > 1:

        cart_item.quantity -= 1

        cart_item.save(
            update_fields=['quantity']
        )

    else:

        cart_item.delete()

    return redirect('cart')


@login_required
@require_POST
def remove_from_cart(request, id):

    cart_item = get_object_or_404(
        CartItem,
        id=id,
        cart__user=request.user
    )

    cart_item.delete()

    return redirect('cart')


# =========================================================
# WISHLIST
# =========================================================

@login_required
@require_POST
def toggle_wishlist(request, id):

    product = get_object_or_404(
        Product,
        id=id
    )

    wishlist_item = Wishlist.objects.filter(
        user=request.user,
        product=product
    ).first()

    if wishlist_item:

        wishlist_item.delete()

    else:

        Wishlist.objects.create(
            user=request.user,
            product=product
        )

    return redirect(
        safe_back_url(request)
    )


@login_required
def wishlist(request):

    wishlist_items = Wishlist.objects.filter(
        user=request.user
    ).select_related(
        'product'
    )

    return render(
        request,
        'products/wishlist.html',
        {
            'wishlist_items': wishlist_items
        }
    )


# =========================================================
# PRODUCT LIST
# =========================================================

def product_list(request):

    query = request.GET.get(
        'q',
        ''
    ).strip()

    sort = request.GET.get(
        'sort',
        ''
    )

    products = Product.objects.all()

    categories = Category.objects.all()

    if query:

        products = products.filter(
            name__icontains=query
        )

    if sort == 'price_low':

        products = products.order_by(
            'price'
        )

    elif sort == 'price_high':

        products = products.order_by(
            '-price'
        )

    elif sort == 'newest':

        products = products.order_by(
            '-created_at'
        )

    else:

        products = products.order_by(
            '-id'
        )

    paginator = Paginator(
        products,
        8
    )

    page_number = request.GET.get(
        'page'
    )

    products = paginator.get_page(
        page_number
    )

    return render(
        request,
        'products/product_list.html',
        {
            'products': products,
            'categories': categories,
            'query': query,
            'sort': sort,
        }
    )


def category_products(request, slug):

    category = get_object_or_404(
        Category,
        slug=slug
    )

    query = request.GET.get(
        'q',
        ''
    ).strip()

    sort = request.GET.get(
        's',
        ''
    )

    products = Product.objects.filter(
        category=category
    )

    categories = Category.objects.all()

    if query:

        products = products.filter(
            name__icontains=query
        )

    if sort == 'price_low':

        products = products.order_by(
            'price'
        )

    elif sort == 'price_high':

        products = products.order_by(
            '-price'
        )

    elif sort == 'newest':

        products = products.order_by(
            '-created_at'
        )

    else:

        products = products.order_by(
            '-id'
        )

    paginator = Paginator(
        products,
        8
    )

    page_number = request.GET.get(
        'page'
    )

    products = paginator.get_page(
        page_number
    )

    return render(
        request,
        'products/product_list.html',
        {
            'products': products,
            'categories': categories,
            'category': category,
            'query': query,
            'sort': sort,
        }
    )


# =========================================================
# PRODUCT DETAIL
# =========================================================

def product_detail(request, id):

    product = get_object_or_404(
        Product,
        id=id
    )

    # =====================================================
    # RECENTLY VIEWED
    # =====================================================

    recent_ids = request.session.get(
        'recently_viewed',
        []
    )

    # Protect against malformed session data
    if not isinstance(recent_ids, list):

        recent_ids = []

    if id in recent_ids:

        recent_ids.remove(id)

    recent_ids.insert(
        0,
        id
    )

    recent_ids = recent_ids[:6]

    request.session[
        'recently_viewed'
    ] = recent_ids

    # =====================================================
    # REVIEWS
    # =====================================================

    reviews = product.reviews.select_related(
        'user'
    ).all()

    average_rating = 0

    if reviews.exists():

        average_rating = (
            sum(
                review.rating
                for review in reviews
            )
            / reviews.count()
        )

    user_review = None

    if request.user.is_authenticated:

        user_review = reviews.filter(
            user=request.user
        ).first()

    # =====================================================
    # RECENT PRODUCTS
    # =====================================================

    recent_products = Product.objects.filter(
        id__in=recent_ids
    ).exclude(
        id=product.id
    )

    recent_products_dict = {
        item.id: item
        for item in recent_products
    }

    recent_products = [
        recent_products_dict[recent_id]
        for recent_id in recent_ids
        if recent_id != id
        and recent_id in recent_products_dict
    ]

    return render(
        request,
        'products/product_detail.html',
        {
            'product': product,
            'reviews': reviews,
            'average_rating': average_rating,
            'user_review': user_review,
            'recent_products': recent_products,
        }
    )


# =========================================================
# AUTHENTICATION
# =========================================================

def register(request):

    if request.method == 'POST':

        username = request.POST.get(
            'username',
            ''
        ).strip()

        password = request.POST.get(
            'password',
            ''
        )

        # =================================================
        # USERNAME VALIDATION
        # =================================================

        if not username:

            return render(
                request,
                'products/register.html',
                {
                    'error':
                        'Username is required.'
                }
            )

        if len(username) > 150:

            return render(
                request,
                'products/register.html',
                {
                    'error':
                        'Username is too long.'
                }
            )

        # =================================================
        # PASSWORD REQUIRED
        # =================================================

        if not password:

            return render(
                request,
                'products/register.html',
                {
                    'error':
                        'Password is required.'
                }
            )

        # =================================================
        # USERNAME DUPLICATE CHECK
        # =================================================

        if User.objects.filter(
            username__iexact=username
        ).exists():

            return render(
                request,
                'products/register.html',
                {
                    'error':
                        'Username already exists.'
                }
            )

        # =================================================
        # STRONG PASSWORD VALIDATION
        # =================================================

        try:

            validate_password(
                password
            )

        except ValidationError as e:

            return render(
                request,
                'products/register.html',
                {
                    'error':
                        ' '.join(e.messages)
                }
            )

        # =================================================
        # CREATE USER
        # =================================================

        user = User.objects.create_user(
            username=username,
            password=password
        )

        # =================================================
        # LOGIN AFTER REGISTRATION
        # =================================================

        login(
            request,
            user
        )

        return redirect(
            'product_list'
        )

    return render(
        request,
        'products/register.html'
    )


def user_login(request):

    if request.method == 'POST':

        username = request.POST.get(
            'username',
            ''
        ).strip()

        password = request.POST.get(
            'password',
            ''
        )

        # =================================================
        # REQUIRED FIELDS
        # =================================================

        if not username or not password:

            return render(
                request,
                'products/login.html',
                {
                    'error':
                        'Username and password are required.'
                }
            )

        # =================================================
        # LOGIN RATE LIMIT
        # =================================================

        if is_login_blocked(
            request,
            username
        ):

            return render(
                request,
                'products/login.html',
                {
                    'error':
                        'Too many failed login attempts. '
                        'Please try again after 15 minutes.'
                }
            )

        # =================================================
        # AUTHENTICATE
        # =================================================

        user = authenticate(
            request,
            username=username,
            password=password
        )

        # =================================================
        # SUCCESS
        # =================================================

        if user is not None:

            clear_login_attempts(
                request,
                username
            )

            login(
                request,
                user
            )

            return redirect(
                'product_list'
            )

        # =================================================
        # FAILED LOGIN
        # =================================================

        record_failed_login(
            request,
            username
        )

        return render(
            request,
            'products/login.html',
            {
                'error':
                    'Invalid username or password.'
            }
        )

    return render(
        request,
        'products/login.html'
    )


@login_required
@require_POST
def user_logout(request):
    logout(request)
    return redirect('product_list')


# =========================================================
# COUPON
# =========================================================

@login_required
@require_POST
def apply_coupon(request):

    code = request.POST.get(
        'coupon_code',
        ''
    ).strip().upper()

    if not code:

        return redirect(
            'checkout'
        )

    coupon = Coupon.objects.filter(
        code=code,
        active=True
    ).first()

    if not coupon:

        return redirect(
            'checkout'
        )

    if coupon.expiry_date < timezone.now():

        return redirect(
            'checkout'
        )

    if coupon.used_count >= coupon.usage_limit:

        return redirect(
            'checkout'
        )

    # Prevent invalid discount values
    if coupon.discount_percent < 0:

        return redirect(
            'checkout'
        )

    if coupon.discount_percent > 100:

        return redirect(
            'checkout'
        )

    request.session[
        'coupon_code'
    ] = coupon.code

    return redirect(
        'checkout'
    )


# =========================================================
# CHECKOUT
# =========================================================

@login_required
def checkout(request):

    cart = Cart.objects.get_or_create(
        user=request.user
    )[0]

    cart_items = cart.items.select_related(
        'product'
    )

    if not cart_items.exists():

        return redirect(
            'cart'
        )

    # =====================================================
    # TOTAL
    # =====================================================

    total = sum(
        (
            item.product.price
            * item.quantity
        )
        for item in cart_items
    )

    # =====================================================
    # COUPON
    # =====================================================

    discount = Decimal('0')

    coupon = None

    coupon_code = request.session.get(
        'coupon_code'
    )

    if coupon_code:

        coupon = Coupon.objects.filter(
            code=coupon_code,
            active=True
        ).first()

        if coupon:

            if (
                coupon.expiry_date >= timezone.now()
                and coupon.used_count < coupon.usage_limit
                and 0 <= coupon.discount_percent <= 100
            ):

                discount = (
                    total
                    * Decimal(
                        coupon.discount_percent
                    )
                ) / Decimal('100')

            else:

                coupon = None

                request.session.pop(
                    'coupon_code',
                    None
                )

    final_total = total - discount

    if final_total < 0:

        final_total = Decimal('0')

    # =====================================================
    # PROFILE
    # =====================================================

    profile, created = UserProfile.objects.get_or_create(
        user=request.user
    )

    # =====================================================
    # POST
    # =====================================================

    if request.method == 'POST':

        # =================================================
        # CUSTOMER INPUT
        # =================================================

        full_name = request.POST.get(
            'full_name',
            ''
        ).strip()

        email = request.POST.get(
            'email',
            ''
        ).strip()

        phone = request.POST.get(
            'phone',
            ''
        ).strip()

        address = request.POST.get(
            'address',
            ''
        ).strip()

        city = request.POST.get(
            'city',
            ''
        ).strip()

        pincode = request.POST.get(
            'pincode',
            ''
        ).strip()

        payment_method = request.POST.get(
            'payment_method',
            ''
        ).strip().lower()

        # =================================================
        # REQUIRED FIELDS
        # =================================================

        if not all(
            [
                full_name,
                email,
                phone,
                address,
                city,
                pincode,
            ]
        ):

            return render(
                request,
                'products/checkout.html',
                checkout_context(
                    cart_items,
                    total,
                    discount,
                    final_total,
                    coupon,
                    profile,
                    'Please fill all required fields.'
                )
            )

        # =================================================
        # LENGTH VALIDATION
        # =================================================

        if len(full_name) > 200:

            return render(
                request,
                'products/checkout.html',
                checkout_context(
                    cart_items,
                    total,
                    discount,
                    final_total,
                    coupon,
                    profile,
                    'Name is too long.'
                )
            )

        if len(address) > 5000:

            return render(
                request,
                'products/checkout.html',
                checkout_context(
                    cart_items,
                    total,
                    discount,
                    final_total,
                    coupon,
                    profile,
                    'Address is too long.'
                )
            )

        if len(city) > 100:

            return render(
                request,
                'products/checkout.html',
                checkout_context(
                    cart_items,
                    total,
                    discount,
                    final_total,
                    coupon,
                    profile,
                    'City name is too long.'
                )
            )

        # =================================================
        # EMAIL VALIDATION
        # =================================================

        try:

            validate_email(email)

        except ValidationError:

            return render(
                request,
                'products/checkout.html',
                checkout_context(
                    cart_items,
                    total,
                    discount,
                    final_total,
                    coupon,
                    profile,
                    'Please enter a valid email address.'
                )
            )

        # =================================================
        # PHONE VALIDATION
        # =================================================

        if (
            not phone.isdigit()
            or len(phone) != 10
            or phone[0] not in '6789'
        ):

            return render(
                request,
                'products/checkout.html',
                checkout_context(
                    cart_items,
                    total,
                    discount,
                    final_total,
                    coupon,
                    profile,
                    'Please enter a valid 10-digit Indian mobile number.'
                )
            )

        # =================================================
        # PINCODE VALIDATION
        # =================================================

        if (
            not pincode.isdigit()
            or len(pincode) != 6
            or pincode[0] == '0'
        ):

            return render(
                request,
                'products/checkout.html',
                checkout_context(
                    cart_items,
                    total,
                    discount,
                    final_total,
                    coupon,
                    profile,
                    'Please enter a valid 6-digit pincode.'
                )
            )

        # =================================================
        # PAYMENT METHOD VALIDATION
        # =================================================

        if payment_method not in [
            'cod',
            'online'
        ]:

            return render(
                request,
                'products/checkout.html',
                checkout_context(
                    cart_items,
                    total,
                    discount,
                    final_total,
                    coupon,
                    profile,
                    'Invalid payment method.'
                )
            )

        # =================================================
        # COD
        # =================================================

        if payment_method == 'cod':

            with transaction.atomic():

                # Lock the cart so two simultaneous
                # checkout requests cannot modify it.
                locked_cart = Cart.objects.select_for_update().get(
                    id=cart.id,
                    user=request.user
                )

                locked_cart_items = list(
                    locked_cart.items.select_related(
                        'product'
                    )
                )

                if not locked_cart_items:

                    return redirect(
                        'cart'
                    )

                # -----------------------------------------
                # LOCK PRODUCTS + CHECK STOCK
                # -----------------------------------------

                locked_products = {}

                for item in locked_cart_items:

                    product = Product.objects.select_for_update().get(
                        id=item.product.id
                    )

                    locked_products[
                        product.id
                    ] = product

                    if item.quantity > product.stock:

                        return render(
                            request,
                            'products/checkout.html',
                            checkout_context(
                                locked_cart_items,
                                total,
                                discount,
                                final_total,
                                coupon,
                                profile,
                                f'{product.name} has only '
                                f'{product.stock} items in stock.'
                            )
                        )

                # -----------------------------------------
                # RECHECK COUPON UNDER LOCK
                # -----------------------------------------

                locked_coupon = None

                if coupon_code:

                    locked_coupon = Coupon.objects.select_for_update().filter(
                        code=coupon_code,
                        active=True
                    ).first()

                    if locked_coupon:

                        if (
                            locked_coupon.expiry_date < timezone.now()
                            or locked_coupon.used_count >= locked_coupon.usage_limit
                            or not (
                                0 <= locked_coupon.discount_percent <= 100
                            )
                        ):

                            locked_coupon = None

                            request.session.pop(
                                'coupon_code',
                                None
                            )

                            discount = Decimal('0')

                            final_total = total

                        else:

                            discount = (
                                total
                                * Decimal(
                                    locked_coupon.discount_percent
                                )
                            ) / Decimal('100')

                            final_total = total - discount

                            if final_total < 0:

                                final_total = Decimal('0')

                # -----------------------------------------
                # CREATE ORDER
                # -----------------------------------------

                order = Order.objects.create(

                    user=request.user,

                    total_amount=final_total,

                    payment_method='cod',

                    payment_status='pending',

                    full_name=full_name,

                    email=email,

                    phone=phone,

                    address=address,

                    city=city,

                    pincode=pincode
                )

                # -----------------------------------------
                # CREATE ITEMS + REDUCE STOCK
                # -----------------------------------------

                for item in locked_cart_items:

                    product = locked_products[
                        item.product.id
                    ]

                    OrderItem.objects.create(

                        order=order,

                        product=product,

                        quantity=item.quantity,

                        price=product.price
                    )

                    product.stock -= item.quantity

                    product.save(
                        update_fields=['stock']
                    )

                # -----------------------------------------
                # CLEAR CART
                # -----------------------------------------

                locked_cart.items.all().delete()

                # -----------------------------------------
                # COUPON USAGE
                # -----------------------------------------

                if locked_coupon:

                    locked_coupon.used_count += 1

                    locked_coupon.save(
                        update_fields=['used_count']
                    )

                request.session.pop(
                    'coupon_code',
                    None
                )

            return redirect(
                'order_success',
                id=order.id
            )

        # =================================================
        # ONLINE PAYMENT
        # =================================================

        if payment_method == 'online':

            razorpay_amount = int(
                final_total
                * Decimal('100')
            )

            # Never allow zero/negative Razorpay orders
            if razorpay_amount <= 0:

                return render(
                    request,
                    'products/checkout.html',
                    checkout_context(
                        cart_items,
                        total,
                        discount,
                        final_total,
                        coupon,
                        profile,
                        'Online payment cannot be used for ₹0 orders.'
                    )
                )

            # ---------------------------------------------
            # FINAL STOCK CHECK
            # ---------------------------------------------

            for item in cart_items:

                if item.quantity > item.product.stock:

                    return render(
                        request,
                        'products/checkout.html',
                        checkout_context(
                            cart_items,
                            total,
                            discount,
                            final_total,
                            coupon,
                            profile,
                            f'{item.product.name} has only '
                            f'{item.product.stock} items in stock.'
                        )
                    )

            # ---------------------------------------------
            # CREATE LOCAL PENDING ORDER
            # ---------------------------------------------

            order = Order.objects.create(

                user=request.user,

                total_amount=final_total,

                payment_method='online',

                payment_status='pending',

                full_name=full_name,

                email=email,

                phone=phone,

                address=address,

                city=city,

                pincode=pincode
            )

            # ---------------------------------------------
            # CREATE ORDER ITEMS
            # ---------------------------------------------

            for item in cart_items:

                OrderItem.objects.create(

                    order=order,

                    product=item.product,

                    quantity=item.quantity,

                    price=item.product.price
                )

            # ---------------------------------------------
            # CREATE RAZORPAY ORDER
            # ---------------------------------------------

            try:

                razorpay_order = razorpay_client.order.create(
                    {
                        'amount': razorpay_amount,
                        'currency': 'INR',
                        'receipt': f'order_{order.id}',
                    }
                )

            except Exception:

                order.delete()

                return render(
                    request,
                    'products/checkout.html',
                    checkout_context(
                        cart_items,
                        total,
                        discount,
                        final_total,
                        coupon,
                        profile,
                        'Unable to start online payment. Please try again.'
                    )
                )

            # ---------------------------------------------
            # SAVE RAZORPAY ORDER ID
            # ---------------------------------------------

            order.razorpay_order_id = (
                razorpay_order['id']
            )

            order.save(
                update_fields=[
                    'razorpay_order_id'
                ]
            )

            return render(
                request,
                'products/checkout.html',
                {
                    'cart_items': cart_items,
                    'total': total,
                    'discount': discount,
                    'final_total': final_total,
                    'coupon': coupon,
                    'profile': profile,

                    'razorpay_order_id':
                        razorpay_order['id'],

                    'razorpay_amount':
                        razorpay_amount,

                    'razorpay_key_id':
                        settings.RAZORPAY_KEY_ID,

                    'order':
                        order,
                }
            )

    # =====================================================
    # GET
    # =====================================================

    return render(
        request,
        'products/checkout.html',
        {
            'cart_items': cart_items,
            'total': total,
            'discount': discount,
            'final_total': final_total,
            'coupon': coupon,
            'profile': profile,
        }
    )


# =========================================================
# RAZORPAY PAYMENT VERIFICATION
# =========================================================

@login_required
@require_POST
def verify_payment(request):

    razorpay_payment_id = request.POST.get(
        'razorpay_payment_id',
        ''
    ).strip()

    razorpay_order_id = request.POST.get(
        'razorpay_order_id',
        ''
    ).strip()

    razorpay_signature = request.POST.get(
        'razorpay_signature',
        ''
    ).strip()

    # =====================================================
    # REQUIRED PAYMENT DATA
    # =====================================================

    if not all(
        [
            razorpay_payment_id,
            razorpay_order_id,
            razorpay_signature,
        ]
    ):

        return JsonResponse(
            {
                'success': False,
                'message':
                    'Payment information is incomplete.'
            },
            status=400
        )

    # =====================================================
    # FIND LOCAL ORDER
    # =====================================================

    order = get_object_or_404(
        Order,
        razorpay_order_id=razorpay_order_id,
        user=request.user,
        payment_method='online'
    )

    # =====================================================
    # ALREADY PAID
    # =====================================================

    if order.payment_status == 'paid':

        return JsonResponse(
            {
                'success': True,

                'redirect_url':
                    f'/products/orders/success/{order.id}/'
            }
        )

    # =====================================================
    # VERIFY RAZORPAY SIGNATURE
    # =====================================================

    try:

        razorpay_client.utility.verify_payment_signature(
            {
                'razorpay_order_id':
                    order.razorpay_order_id,

                'razorpay_payment_id':
                    razorpay_payment_id,

                'razorpay_signature':
                    razorpay_signature,
            }
        )

    except razorpay.errors.SignatureVerificationError:

        order.payment_status = 'failed'

        order.save(
            update_fields=[
                'payment_status'
            ]
        )

        return JsonResponse(
            {
                'success': False,
                'message':
                    'Payment verification failed.'
            },
            status=400
        )

    except Exception:

        return JsonResponse(
            {
                'success': False,
                'message':
                    'Unable to verify payment.'
            },
            status=400
        )

    # =====================================================
    # FETCH PAYMENT DIRECTLY FROM RAZORPAY
    # =====================================================

    try:

        payment = razorpay_client.payment.fetch(
            razorpay_payment_id
        )

    except Exception:

        return JsonResponse(
            {
                'success': False,
                'message':
                    'Unable to verify payment status.'
            },
            status=400
        )

    # =====================================================
    # VERIFY PAYMENT BELONGS TO OUR RAZORPAY ORDER
    # =====================================================

    fetched_order_id = payment.get(
        'order_id'
    )

    if fetched_order_id != order.razorpay_order_id:

        order.payment_status = 'failed'

        order.save(
            update_fields=[
                'payment_status'
            ]
        )

        return JsonResponse(
            {
                'success': False,
                'message':
                    'Payment order mismatch.'
            },
            status=400
        )

    # =====================================================
    # VERIFY AMOUNT
    # =====================================================

    expected_amount = int(
        order.total_amount
        * Decimal('100')
    )

    paid_amount = int(
        payment.get(
            'amount',
            0
        )
    )

    if paid_amount != expected_amount:

        order.payment_status = 'failed'

        order.save(
            update_fields=[
                'payment_status'
            ]
        )

        return JsonResponse(
            {
                'success': False,
                'message':
                    'Payment amount mismatch.'
            },
            status=400
        )

    # =====================================================
    # VERIFY CURRENCY
    # =====================================================

    if payment.get('currency') != 'INR':

        order.payment_status = 'failed'

        order.save(
            update_fields=[
                'payment_status'
            ]
        )

        return JsonResponse(
            {
                'success': False,
                'message':
                    'Invalid payment currency.'
            },
            status=400
        )

    # =====================================================
    # VERIFY PAYMENT STATUS
    # =====================================================

    if payment.get('status') != 'captured':

        return JsonResponse(
            {
                'success': False,
                'message':
                    'Payment has not been captured yet.'
            },
            status=400
        )

    # =====================================================
    # PAYMENT SUCCESS
    # =====================================================

    with transaction.atomic():

        # Lock the order so the same payment cannot
        # fulfil the order twice simultaneously.
        order = Order.objects.select_for_update().get(
            id=order.id,
            user=request.user
        )

        if order.payment_status == 'paid':

            return JsonResponse(
                {
                    'success': True,

                    'redirect_url':
                        f'/products/orders/success/{order.id}/'
                }
            )

        # ---------------------------------------------
        # LOCK PRODUCTS + STOCK CHECK
        # ---------------------------------------------

        order_items = list(
            order.items.select_related(
                'product'
            )
        )

        locked_products = {}

        for item in order_items:

            product = Product.objects.select_for_update().get(
                id=item.product.id
            )

            locked_products[
                product.id
            ] = product

            if item.quantity > product.stock:

                # Payment was captured, but inventory is
                # unavailable. We do NOT pretend the order
                # was successfully fulfilled.
                return JsonResponse(
                    {
                        'success': False,
                        'message':
                            f'{product.name} is no longer available '
                            f'in the requested quantity. '
                            f'Please contact support for payment resolution.'
                    },
                    status=409
                )

        # ---------------------------------------------
        # MARK PAYMENT PAID
        # ---------------------------------------------

        order.razorpay_payment_id = (
            razorpay_payment_id
        )

        order.razorpay_signature = (
            razorpay_signature
        )

        order.payment_status = 'paid'

        order.save(
            update_fields=[
                'razorpay_payment_id',
                'razorpay_signature',
                'payment_status',
            ]
        )

        # ---------------------------------------------
        # REDUCE STOCK
        # ---------------------------------------------

        for item in order_items:

            product = locked_products[
                item.product.id
            ]

            product.stock -= item.quantity

            product.save(
                update_fields=['stock']
            )

        # ---------------------------------------------
        # CLEAR USER CART
        # ---------------------------------------------

        cart = Cart.objects.select_for_update().get(
            user=request.user
        )

        cart.items.all().delete()

        # ---------------------------------------------
        # COUPON USAGE
        # ---------------------------------------------

        coupon_code = request.session.get(
            'coupon_code'
        )

        if coupon_code:

            coupon = Coupon.objects.select_for_update().filter(
                code=coupon_code,
                active=True
            ).first()

            if coupon:

                # Only increment if usage is still available.
                if coupon.used_count < coupon.usage_limit:

                    coupon.used_count += 1

                    coupon.save(
                        update_fields=['used_count']
                    )

        request.session.pop(
            'coupon_code',
            None
        )

    return JsonResponse(
        {
            'success': True,

            'redirect_url':
                f'/products/orders/success/{order.id}/'
        }
    )


# =========================================================
# ORDER SUCCESS
# =========================================================

@login_required
def order_success(request, id):

    order = get_object_or_404(
        Order,
        id=id,
        user=request.user
    )

    return render(
        request,
        'products/order_success.html',
        {
            'order': order
        }
    )


# =========================================================
# MY ORDERS
# =========================================================

@login_required
def my_orders(request):

    orders = Order.objects.filter(
        user=request.user
    ).order_by(
        '-created_at'
    )

    return render(
        request,
        'products/my_orders.html',
        {
            'orders': orders
        }
    )


# =========================================================
# ORDER DETAIL
# =========================================================

@login_required
def order_detail(request, id):

    order = get_object_or_404(
        Order,
        id=id,
        user=request.user
    )

    order_items = order.items.select_related(
        'product'
    )

    return render(
        request,
        'products/order_detail.html',
        {
            'order': order,
            'order_items': order_items,
        }
    )


# =========================================================
# REVIEWS
# =========================================================

@login_required
@require_POST
def add_review(request, id):

    product = get_object_or_404(
        Product,
        id=id
    )

    rating_raw = request.POST.get(
        'rating',
        ''
    ).strip()

    comment = request.POST.get(
        'comment',
        ''
    ).strip()

    # =====================================================
    # RATING VALIDATION
    # =====================================================

    try:

        rating = int(rating_raw)

    except (TypeError, ValueError):

        return redirect(
            'product_detail',
            id=product.id
        )

    if rating < 1 or rating > 5:

        return redirect(
            'product_detail',
            id=product.id
        )

    # =====================================================
    # COMMENT VALIDATION
    # =====================================================

    if not comment:

        return redirect(
            'product_detail',
            id=product.id
        )

    if len(comment) > 2000:

        return redirect(
            'product_detail',
            id=product.id
        )

    # =====================================================
    # CREATE / UPDATE REVIEW
    # =====================================================

    Review.objects.update_or_create(

        user=request.user,

        product=product,

        defaults={
            'rating': rating,
            'comment': comment
        }
    )

    return redirect(
        'product_detail',
        id=product.id
    )


# =========================================================
# PROFILE
# =========================================================

@login_required
def profile(request):

    profile, created = UserProfile.objects.get_or_create(
        user=request.user
    )

    if request.method == 'POST':

        email = request.POST.get(
            'email',
            ''
        ).strip()

        full_name = request.POST.get(
            'full_name',
            ''
        ).strip()

        phone = request.POST.get(
            'phone',
            ''
        ).strip()

        address = request.POST.get(
            'address',
            ''
        ).strip()

        city = request.POST.get(
            'city',
            ''
        ).strip()

        pincode = request.POST.get(
            'pincode',
            ''
        ).strip()

        # =================================================
        # EMAIL
        # =================================================

        try:

            validate_email(email)

        except ValidationError:

            return render(
                request,
                'products/profile.html',
                {
                    'profile': profile,
                    'error':
                        'Please enter a valid email address.'
                }
            )

        # =================================================
        # FIELD LENGTHS
        # =================================================

        if len(full_name) > 200:

            return render(
                request,
                'products/profile.html',
                {
                    'profile': profile,
                    'error':
                        'Name is too long.'
                }
            )

        if len(address) > 5000:

            return render(
                request,
                'products/profile.html',
                {
                    'profile': profile,
                    'error':
                        'Address is too long.'
                }
            )

        if len(city) > 100:

            return render(
                request,
                'products/profile.html',
                {
                    'profile': profile,
                    'error':
                        'City name is too long.'
                }
            )

        # =================================================
        # PHONE
        # =================================================

        if phone:

            if (
                not phone.isdigit()
                or len(phone) != 10
                or phone[0] not in '6789'
            ):

                return render(
                    request,
                    'products/profile.html',
                    {
                        'profile': profile,
                        'error':
                            'Please enter a valid 10-digit phone number.'
                    }
                )

        # =================================================
        # PINCODE
        # =================================================

        if pincode:

            if (
                not pincode.isdigit()
                or len(pincode) != 6
                or pincode[0] == '0'
            ):

                return render(
                    request,
                    'products/profile.html',
                    {
                        'profile': profile,
                        'error':
                            'Please enter a valid 6-digit pincode.'
                    }
                )

        # =================================================
        # SAVE
        # =================================================

        request.user.email = email

        request.user.save(
            update_fields=['email']
        )

        profile.full_name = full_name

        profile.phone = phone

        profile.address = address

        profile.city = city

        profile.pincode = pincode

        profile.save()

        return redirect(
            'profile'
        )

    return render(
        request,
        'products/profile.html',
        {
            'profile': profile
        }
    )