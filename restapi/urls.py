from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework.authtoken import views

from restapi.views import user_view_set, category_view_set, group_view_set, expenses_view_set, index, logout, balance, \
    logProcessor

    
router = DefaultRouter()
router.register('users', user_view_set)
router.register('categories', category_view_set)
router.register('groups', group_view_set)
router.register('expenses', expenses_view_set)

url_patterns = [
    path('', index, name='index'),
    path('auth/logout/', logout),
    path('auth/login/', views.obtain_auth_token),
    path('balances/', balance),
    path('process-logs/', logProcessor)
]

url_patterns += router.urls
