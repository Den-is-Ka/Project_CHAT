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
