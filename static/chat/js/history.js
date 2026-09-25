let historyLoading = false;
let historyHasMore = true;
let historyScrollTimer = null;
let historyScrollSuppressed = false;

const HISTORY_SCROLL_THRESHOLD = 80;
const HISTORY_SCROLL_DEBOUNCE_MS = 150;


function getOldestRenderedMessageId() {

    if (!chatLog) {
        return null;
    }

    const oldestMessage =
        chatLog.querySelector(
            "[data-message-id]"
        );

    if (!oldestMessage) {
        return null;
    }

    const messageId =
        Number(
            oldestMessage.dataset.messageId
        );

    return Number.isInteger(messageId) && messageId > 0
        ? messageId
        : null;
}


async function loadOlderMessages() {

    if (
        !chatLog
        ||
        !isAuthenticated
        ||
        !chatConfig.isRoomMember
        ||
        !chatConfig.historyUrl
        ||
        historyLoading
        ||
        !historyHasMore
    ) {
        return;
    }

    const beforeId =
        getOldestRenderedMessageId();

    if (!beforeId) {
        return;
    }

    historyLoading = true;

    clearTimeout(historyScrollTimer);
    historyScrollTimer = null;
    historyScrollSuppressed = true;

    const previousScrollHeight =
        chatLog.scrollHeight;

    const previousScrollTop =
        chatLog.scrollTop;

    const anchor =
        chatLog.querySelector(
            "[data-message-id]"
        );

    try {

        const url =
            new URL(
                chatConfig.historyUrl,
                window.location.origin
            );

        url.searchParams.set(
            "before",
            String(beforeId)
        );

        const response =
            await apiRequest(
                url.toString(),
                {
                    method: "GET",
                }
            );

        if (!response.ok) {
            console.error(
                "History load failed:",
                response.status
            );
            return;
        }

        const data =
            await response.json();

        const messages =
            Array.isArray(data.messages)
                ? data.messages
                : [];

        messages.forEach(
            function (messageData) {

                if (!addMessage(messageData)) {
                    return;
                }

                const messageElement =
                    chatLog.querySelector(
                        `[data-message-id="${String(messageData.id)}"]`
                    );

                if (
                    messageElement
                    &&
                    anchor
                ) {
                    chatLog.insertBefore(
                        messageElement,
                        anchor
                    );
                }
            }
        );

        historyHasMore =
            Boolean(data.has_more);

        const scrollDelta =
            chatLog.scrollHeight
            -
            previousScrollHeight;

        chatLog.scrollTop =
            previousScrollTop
            +
            scrollDelta;

    } catch (error) {

        console.error(
            "History load error:",
            error
        );

    } finally {

        historyLoading = false;

        setTimeout(
            function () {
                historyScrollSuppressed = false;
            },
            HISTORY_SCROLL_DEBOUNCE_MS
        );
    }
}


if (
    chatLog
    &&
    isAuthenticated
    &&
    chatConfig.isRoomMember
) {

    chatLog.addEventListener(
        "scroll",
        function () {

            if (historyScrollSuppressed) {
                return;
            }

            clearTimeout(
                historyScrollTimer
            );

            historyScrollTimer =
                setTimeout(
                    function () {

                        if (
                            chatLog.scrollTop
                            <=
                            HISTORY_SCROLL_THRESHOLD
                        ) {
                            loadOlderMessages();
                        }
                    },
                    HISTORY_SCROLL_DEBOUNCE_MS
                );
        }
    );
}


// ==================================================
// Browser notifications
// ==================================================

createBrowserNotificationButton();
installBrowserNotificationHandler();


function createBrowserNotificationButton() {

    if (!isAuthenticated) {
        return;
    }

    const dropdown =
        document.getElementById(
            "user-menu-dropdown"
        );

    if (!dropdown) {
        return;
    }

    let button =
        document.getElementById(
            "browser-notifications-button"
        );

    if (!button) {
        button =
            document.createElement("button");

        button.type = "button";
        button.id =
            "browser-notifications-button";
        button.className =
            "user-menu-item";

        const logoutForm =
            document.getElementById(
                "logout-form"
            );

        dropdown.insertBefore(
            button,
            logoutForm || null
        );

        button.addEventListener(
            "click",
            requestBrowserNotifications
        );
    }

    updateBrowserNotificationButton();
}


function updateBrowserNotificationButton() {

    const button =
        document.getElementById(
            "browser-notifications-button"
        );

    if (!button) {
        return;
    }

    if (!("Notification" in window)) {
        button.textContent =
            "🔕 Уведомления недоступны";
        button.disabled = true;
        return;
    }

    button.disabled = false;

    if (Notification.permission === "granted") {
        button.textContent =
            "🔔 Уведомления включены";
        return;
    }

    if (Notification.permission === "denied") {
        button.textContent =
            "🔕 Уведомления запрещены";
        return;
    }

    button.textContent =
        "🔔 Включить уведомления";
}


function showNotificationFeedback(
    message,
    type
) {

    if (typeof showToast === "function") {
        showToast(message, type);
        return;
    }

    console.log(message);
}


async function requestBrowserNotifications() {

    if (!("Notification" in window)) {
        showNotificationFeedback(
            "Системные уведомления недоступны в этом браузере.",
            "error"
        );
        return;
    }

    if (Notification.permission === "granted") {
        showNotificationFeedback(
            "Системные уведомления уже включены.",
            "ok"
        );
        return;
    }

    if (Notification.permission === "denied") {
        showNotificationFeedback(
            "Уведомления заблокированы в настройках браузера.",
            "error"
        );
        return;
    }

    try {
        await Notification.requestPermission();
    } catch (error) {
        console.error(
            "Notification permission error:",
            error
        );
    }

    updateBrowserNotificationButton();

    if (Notification.permission === "granted") {
        showNotificationFeedback(
            "Системные уведомления включены.",
            "ok"
        );
    } else {
        showNotificationFeedback(
            "Разрешение на уведомления не выдано.",
            "error"
        );
    }
}


function trimNotificationText(text) {

    const value =
        String(text || "").trim();

    if (value.length <= 160) {
        return value;
    }

    return value.slice(0, 157) + "…";
}


function showBrowserNotification(
    title,
    body,
    targetUrl,
    tag
) {

    if (
        !("Notification" in window)
        ||
        Notification.permission !== "granted"
    ) {
        return;
    }

    const notification =
        new Notification(
            title,
            {
                body: trimNotificationText(body),
                tag: tag || undefined,
            }
        );

    notification.onclick =
        function () {

            window.focus();

            if (targetUrl) {
                window.location.href =
                    targetUrl;
            }

            notification.close();
        };
}


function getRoomLink(roomId) {

    return document.querySelector(
        `.rooms-list .room-link[data-room-id="${String(roomId)}"]`
    );
}


function getRoomDisplayName(link) {

    const name =
        link?.querySelector(
            ".room-name"
        )?.textContent;

    return String(name || "Чат").trim();
}


function messageNotificationBody(data) {

    if (data?.message) {
        return data.message;
    }

    if (data?.attachment_name) {
        return `Файл: ${data.attachment_name}`;
    }

    if (data?.attachment) {
        return "Новое вложение";
    }

    return "Новое сообщение";
}


function handleLiveBrowserNotification(data) {

    if (
        !data
        ||
        data.username === chatConfig.username
    ) {
        return;
    }

    const roomTitle =
        document.getElementById(
            "room-title-name"
        )?.textContent?.trim()
        || chatConfig.roomName;

    showBrowserNotification(
        `${data.username} • ${roomTitle}`,
        messageNotificationBody(data),
        window.location.href,
        `chat-message-${data.id}`
    );
}


function handleOtherRoomBrowserNotification(data) {

    if (
        !data
        ||
        Number(data.room_id)
            === Number(chatConfig.roomId)
        ||
        Number(data.unread_count) <= 0
    ) {
        return;
    }

    const link =
        getRoomLink(data.room_id);

    if (!link) {
        return;
    }

    const roomName =
        getRoomDisplayName(link);

    showBrowserNotification(
        `Новое сообщение • ${roomName}`,
        `Непрочитанных сообщений: ${data.unread_count}`,
        link.href,
        `chat-room-${data.room_id}`
    );
}


function installBrowserNotificationHandler() {

    if (
        !isAuthenticated
        ||
        typeof handleWebSocketMessage
            !== "function"
    ) {
        return;
    }

    const originalHandler =
        handleWebSocketMessage;

    handleWebSocketMessage =
        function (event) {

            let data = null;

            try {
                data = JSON.parse(event.data);
            } catch (error) {
                data = null;
            }

            originalHandler(event);

            if (!data) {
                return;
            }

            if (
                data.type === "message"
                &&
                document.hidden
            ) {
                handleLiveBrowserNotification(data);
                return;
            }

            if (data.type === "unread_update") {
                handleOtherRoomBrowserNotification(data);
            }
        };

    if (chatSocket) {
        chatSocket.onmessage =
            handleWebSocketMessage;
    }
}
