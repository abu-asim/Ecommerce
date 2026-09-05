from django.urls import path
from . import views

urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('category/<slug:slug>/', views.category_products, name='category_products'),
    path('<int:id>/',views.product_detail, name='product_detail'),
    path('<int:id>/add-to-cart/',views.add_to_cart, name='add_to_cart'),
    path('cart/', views.cart, name='cart'),
    path('register/', views.register, name='register'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('checkout/', views.checkout, name='checkout'),
    path('my-orders/',views.my_orders,name='my_orders'),
    path('cart/increase/<int:id>/',views.increase_quantity,name='increase_quantity'),
    path('cart/decrease/<int:id>/',views.decrease_quantity,name='decrease_quantity'),
    path('cart/remove/<int:id>/',views.remove_from_cart,name='remove_from_cart'),
    path('order-success/<int:id>/',views.order_success,name='order_success'),
    path('order-detail/<int:id>/',views.order_detail,name='order_detail'),
    path('wishlist/',views.wishlist,name='wishlist'),
    path('wishlist/toggle/<int:id>',views.toggle_wishlist,name='toggle_wishlist'),
    path('review/add/<int:id>/',views.add_review,name='add_review'),
    path('profile/',views.profile,name='profile'),
    path('apply-coupon/',views.apply_coupon,name='apply_coupon'),
    path('payment/verify/',views.verify_payment,name='verify_payment'),
]