from django.urls import path
from ai_assistant import views

app_name = 'ai_assistant'

urlpatterns = [
    # AI Assistant Chat
    path('chat/', views.AIAssistantChatView.as_view(), name='chat'),
    path('chat/<uuid:conv_id>/', views.AIAssistantChatView.as_view(), name='chat_conversation'),

    # Risk & Anomaly Intelligence Center
    path('risks/', views.ManagementRiskCenterView.as_view(), name='risk_center'),
    path('risks/<uuid:pk>/resolve/', views.RiskResolveView.as_view(), name='risk_resolve'),
    path('risks/scan/', views.RunRiskScanNowView.as_view(), name='risk_scan'),

    # Executive Briefing Reports
    path('briefings/', views.ExecutiveBriefingListView.as_view(), name='briefing_list'),
    path('briefings/generate/', views.GenerateBriefingNowView.as_view(), name='briefing_generate'),
    path('briefings/<uuid:pk>/', views.ExecutiveBriefingDetailView.as_view(), name='briefing_detail'),
]
