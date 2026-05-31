from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('songs/', views.songs, name='songs'),
    path('songs/detail/', views.song_detail, name='song_detail'),
    path('artists/detail/', views.artist_detail, name='artist_detail'),
    path('countries/detail/', views.country_detail, name='country_detail'),
    path('operations/', views.operations, name='operations'),
    path('insights/', views.insights, name='insights'),
    path('billboard/', views.billboard, name='billboard'),
    path('about-data/', views.about_data, name='about_data'),
]
