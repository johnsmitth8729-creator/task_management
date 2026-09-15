from django.urls import path

from .views import (
    ProfileEditView,
    ProfileView,
    UserCreateView,
    UserDeleteView,
    UserDetailView,
    UserListView,
    UserLoginView,
    UserLogoutView,
    UserToggleActiveView,
    UserUpdateView,
)

urlpatterns = [
    path('login/', UserLoginView.as_view(), name='login'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    # Profile
    path('profile/', ProfileView.as_view(), name='profile'),
    path('profile/edit/', ProfileEditView.as_view(), name='profile_edit'),
    # User Management
    path('users/', UserListView.as_view(), name='user_list'),
    path('users/create/', UserCreateView.as_view(), name='user_create'),
    path('users/<uuid:pk>/', UserDetailView.as_view(), name='user_detail'),
    path('users/<uuid:pk>/edit/', UserUpdateView.as_view(), name='user_edit'),
    path('users/<uuid:pk>/delete/', UserDeleteView.as_view(), name='user_delete'),
    path('users/<uuid:pk>/toggle-active/', UserToggleActiveView.as_view(), name='user_toggle_active'),
]
