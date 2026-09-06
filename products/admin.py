from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Product,
    Category,
    CartItem,
    Order,
    OrderItem,
    UserProfile,
    Coupon,
    Wishlist,
    Review,
)


# =====================================================
# PRODUCT ADMIN
# =====================================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):

    list_display = (
        'product_image',
        'name',
        'category',
        'price',
        'stock_status',
        'created_at',
    )

    list_filter = (
        'category',
        'created_at',
    )

    search_fields = (
        'name',
    )

    ordering = (
        '-created_at',
    )

    list_per_page = 20

    fieldsets = (
        (
            '🛍️ Product Information',
            {
                'fields': (
                    'name',
                    'category',
                )
            }
        ),
        (
            '💰 Pricing & Inventory',
            {
                'fields': (
                    'price',
                    'stock',
                )
            }
        ),
        (
            '📝 Product Description',
            {
                'fields': (
                    'discription',
                )
            }
        ),
        (
            '🖼️ Product Image',
            {
                'fields': (
                    'image',
                    'image_preview',
                )
            }
        ),
    )

    readonly_fields = (
        'image_preview',
    )

    def product_image(self, obj):

        if obj.image:
            return format_html(
                '<img src="{}" class="admin-product-thumb">',
                obj.image.url
            )

        return format_html(
            '<span class="admin-no-image">{}</span>',
            '📦'
        )

    product_image.short_description = 'Image'

    def image_preview(self, obj):

        if obj.image:
            return format_html(
                '''
                <div class="admin-image-preview">
                    <img src="{}">
                    <span>Current Product Image</span>
                </div>
                ''',
                obj.image.url
            )

        return format_html(
            '<div class="admin-no-preview">{}</div>',
            '📦 No image uploaded'
        )

    image_preview.short_description = 'Preview'

    def stock_status(self, obj):

        if obj.stock == 0:

            return format_html(
                '<span class="stock-badge stock-out">{}</span>',
                '❌ Out of Stock'
            )

        elif obj.stock <= 5:

            return format_html(
                '<span class="stock-badge stock-low">⚠️ {} left</span>',
                obj.stock
            )

        return format_html(
            '<span class="stock-badge stock-good">✅ {} in stock</span>',
            obj.stock
        )

    stock_status.short_description = 'Stock'


# =====================================================
# CATEGORY ADMIN
# =====================================================

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):

    list_display = (
        'name',
        'slug',
    )

    search_fields = (
        'name',
        'slug',
    )

    prepopulated_fields = {
        'slug': ('name',)
    }


# =====================================================
# ORDER ADMIN
# =====================================================

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'user',
        'full_name',
        'total_amount',
        'payment_method',
        'payment_status',
        'status',
        'created_at',
    )

    list_filter = (
        'status',
        'payment_method',
        'payment_status',
        'created_at',
    )

    search_fields = (
        'user__username',
        'full_name',
        'email',
        'phone',
        'razorpay_order_id',
        'razorpay_payment_id',
    )

    ordering = (
        '-created_at',
    )

    list_per_page = 20

    fieldsets = (
        (
            '📦 Order Information',
            {
                'fields': (
                    'user',
                    'total_amount',
                    'status',
                    'created_at',
                )
            }
        ),
        (
            '💳 Payment Information',
            {
                'fields': (
                    'payment_method',
                    'payment_status',
                )
            }
        ),
        (
            '👤 Customer Details',
            {
                'fields': (
                    'full_name',
                    'email',
                    'phone',
                    'address',
                    'city',
                    'pincode',
                )
            }
        ),
        (
            '🔐 Razorpay Details',
            {
                'fields': (
                    'razorpay_order_id',
                    'razorpay_payment_id',
                    'razorpay_signature',
                )
            }
        ),
    )

    readonly_fields = (
        'user',
        'total_amount',
        'created_at',
        'razorpay_order_id',
        'razorpay_payment_id',
        'razorpay_signature',
    )


# =====================================================
# ORDER ITEM ADMIN
# =====================================================

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):

    list_display = (
        'order',
        'product',
        'quantity',
        'price',
    )

    search_fields = (
        'product__name',
        'order__user__username',
    )


# =====================================================
# CART ITEM ADMIN
# =====================================================

@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):

    list_display = (
        'cart',
        'product',
        'quantity',
    )

    search_fields = (
        'product__name',
        'cart__user__username',
    )


# =====================================================
# USER PROFILE ADMIN
# =====================================================

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):

    list_display = (
        'user',
        'full_name',
        'phone',
        'city',
        'pincode',
    )

    search_fields = (
        'user__username',
        'full_name',
        'phone',
        'city',
        'pincode',
    )


# =====================================================
# COUPON ADMIN
# =====================================================

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):

    list_display = (
        'code',
        'discount_percent',
        'active',
        'expiry_date',
        'usage_limit',
        'used_count',
    )

    list_filter = (
        'active',
        'expiry_date',
    )

    search_fields = (
        'code',
    )

    ordering = (
        '-expiry_date',
    )


# =====================================================
# WISHLIST ADMIN
# =====================================================

@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):

    list_display = (
        'user',
        'product',
        'created_at',
    )

    search_fields = (
        'user__username',
        'product__name',
    )

    ordering = (
        '-created_at',
    )


# =====================================================
# REVIEW ADMIN
# =====================================================

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):

    list_display = (
        'user',
        'product',
        'rating_display',
        'created_at',
    )

    list_filter = (
        'rating',
        'created_at',
    )

    search_fields = (
        'user__username',
        'product__name',
        'comment',
    )

    ordering = (
        '-created_at',
    )

    def rating_display(self, obj):

        stars = '★' * obj.rating + '☆' * (5 - obj.rating)

        return format_html(
            '<span class="admin-rating">{}</span>',
            stars
        )

    rating_display.short_description = 'Rating'