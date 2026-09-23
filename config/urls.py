from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from chat.attachments import ProtectedChatAttachmentView
from config import settings
from config.views import home

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "media/chat_files/<path:attachment_path>",
        ProtectedChatAttachmentView.as_view(),
        name="protected_chat_attachment",
    ),
    path("chat/", include("chat.urls")),
    path("users/", include("users.urls")),
    path("", home, name="home"),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
