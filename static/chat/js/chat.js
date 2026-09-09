const roomName = chatConfig.roomName;

let chatSocket = null;
let reconnectTimeout = null;
let shouldReconnect = true;

let reconnectAttempts = 0;

const RECONNECT_BASE_DELAY = 1000;
const RECONNECT_MAX_DELAY = 10000;

let pendingMessages = [];

const isAuthenticated = chatConfig.isAuthenticated;


// ==================================================
// DOM
// ==================================================

const loginContainer =
    document.getElementById("login-container");

const registerContainer =
    document.getElementById("register-container");

const loginForm =
    document.getElementById("login-form");

const registerForm =
    document.getElementById("register-form");

const showRegisterButton =
    document.getElementById("show-register");

const showLoginButton =
    document.getElementById("show-login");

const chatLog =
    document.getElementById("chat-log");


// ==================================================
// Common helpers
// ==================================================

function getCsrfToken() {

    const csrfInput =
        document.querySelector(
            "[name=csrfmiddlewaretoken]"
        );

    return csrfInput
        ? csrfInput.value
        : "";
}


function showError(message) {

    const errorElement =
        document.getElementById("login-error")
        ||
        document.getElementById("register-error");

    if (!errorElement) {
        return;
    }

    errorElement.textContent = message;

    setTimeout(function () {
        errorElement.textContent = "";
    }, 4000);
}


function extractFormErrors(errors) {

    if (!errors) {
        return "";
    }

    const messages = [];

    for (const field in errors) {

        const fieldErrors =
            errors[field];

        if (Array.isArray(fieldErrors)) {

            fieldErrors.forEach(function (error) {

                messages.push(
                    typeof error === "object"
                        ? error.message
                        : error
                );
            });

        } else {

            messages.push(fieldErrors);
        }
    }

    return messages.join(" • ");
}


async function apiRequest(
    url,
    options = {}
) {

    const headers = {
        "X-CSRFToken": getCsrfToken(),
        ...(options.headers || {}),
    };

    return fetch(
        url,
        {
            ...options,
            headers,
        }
    );
}


// ==================================================
// Modal helpers
// ==================================================

function openModal(modal) {

    if (!modal) {
        return;
    }

    modal.classList.remove("hidden");
}


function closeModal(modal) {

    if (!modal) {
        return;
    }

    modal.classList.add("hidden");
}


function showModalError(
    element,
    message
) {

    if (!element) {
        return;
    }

    element.textContent = message;

    element.classList.remove("hidden");
}


function clearModalError(element) {

    if (!element) {
        return;
    }

    element.textContent = "";

    element.classList.add("hidden");
}


// ==================================================
// WebSocket
// ==================================================

if (isAuthenticated) {
    connectWebSocket();
}


function connectWebSocket() {

    if (!shouldReconnect) {
        return;
    }

    const protocol =
        window.location.protocol === "https:"
            ? "wss:"
            : "ws:";

    chatSocket =
        new WebSocket(
            `${protocol}//${window.location.host}/ws/chat/${encodeURIComponent(roomName)}/`
        );


    chatSocket.onmessage =
        handleWebSocketMessage;


    chatSocket.onclose =
        handleWebSocketClose;


    chatSocket.onopen =
        function () {

            reconnectAttempts = 0;

            flushPendingMessages();
        };


    chatSocket.onerror =
        function (error) {

            console.error(
                "WebSocket error:",
                error
            );
        };
}


function flushPendingMessages() {

    if (
        !chatSocket
        ||
        chatSocket.readyState !== WebSocket.OPEN
    ) {
        return;
    }

    while (pendingMessages.length) {

        chatSocket.send(
            JSON.stringify(
                pendingMessages.shift()
            )
        );
    }
}


// Heartbeat: держим соединение живым, чтобы его не закрывали
// прокси/балансировщики по idle-timeout.
setInterval(function () {

    if (
        chatSocket
        &&
        chatSocket.readyState === WebSocket.OPEN
    ) {

        chatSocket.send(
            JSON.stringify({
                type: "ping",
            })
        );
    }
}, 25000);


function handleWebSocketMessage(event) {

    const data =
        JSON.parse(event.data);


    switch (data.type) {

        case "history":

            let addedMessages =
                false;

            data.messages.forEach(
                function (messageData) {

                    if (addMessage(messageData)) {
                        addedMessages = true;
                    }
                }
            );

            // Скроллим вниз только если появились новые сообщения
            // (чтобы не сбрасывать позицию при переподключении).
            if (addedMessages) {
                scrollToBottom(false);
            }

            break;


        case "message":

            addMessage(data);

            scrollToBottom(true);

            markCurrentRoomRead();

            break;


        case "error":

            showError(data.message);

            break;


        case "online_users":

            updateOnlineUsers(
                data.users
            );

            break;


        case "user_status":

            showSystemMessage(
                data.username,
                data.action
            );

            scrollToBottom(true);

            break;


        case "reaction":

            updateMessageReactions(
                data.message_id,
                data.reactions || []
            );

            break;


        case "unread_update":

            applyUnreadUpdate(data);

            break;


        case "message_updated":

            updateMessage(data);

            break;


        case "message_deleted":

            removeMessageElement(data.message_id);

            break;


        default:

            console.warn(
                "Unknown WebSocket message:",
                data
            );
    }
}


function handleWebSocketClose(event) {

    console.log(
        "WebSocket connection closed"
    );

    if (!shouldReconnect) {
        return;
    }

    // 4000 — комната не найдена, 4001 — нет доступа.
    // Переподключаться бессмысленно.
    if (
        event.code === 4000
        ||
        event.code === 4001
    ) {
        shouldReconnect = false;
        return;
    }

    clearTimeout(
        reconnectTimeout
    );

    // Экспоненциальная задержка с ограничением сверху.
    const delay =
        Math.min(
            RECONNECT_BASE_DELAY
                * Math.pow(2, reconnectAttempts),
            RECONNECT_MAX_DELAY
        );

    reconnectAttempts += 1;

    reconnectTimeout =
        setTimeout(
            connectWebSocket,
            delay
        );
}


// При реальной навигации/закрытии вкладки прекращаем
// переподключения, чтобы "старая" страница не открывала
// второй сокет в момент загрузки новой.
window.addEventListener(
    "pagehide",
    function () {

        shouldReconnect = false;

        clearTimeout(
            reconnectTimeout
        );

        if (chatSocket) {

            chatSocket.onclose = null;

            chatSocket.close();
        }
    }
);


// Возврат из bfcache (назад/вперёд) — страница осталась живой,
// но сокет мёртв: открываем его заново.
window.addEventListener(
    "pageshow",
    function (event) {

        if (event.persisted) {

            shouldReconnect = true;

            connectWebSocket();
        }
    }
);


// ==================================================
// Online users
// ==================================================

function updateOnlineUsers(users) {

    const onlineUsers =
        new Set(users);

    const members =
        document.querySelectorAll(
            ".room-member"
        );


    members.forEach(function (member) {

        const username =
            member.dataset.username;

        const status =
            member.querySelector(
                ".participant-status"
            );

        if (!status) {
            return;
        }

        status.classList.toggle(
            "online",
            onlineUsers.has(username)
        );
    });
}


// ==================================================
// Messages
// ==================================================

function addMessage(data) {

    if (!chatLog) {
        return false;
    }

    // Защита от дублей: после переподключения сервер повторно
    // присылает историю — сообщение с уже отрисованным id
    // просто пропускаем.
    if (data.id) {

        const existing =
            chatLog.querySelector(
                `[data-message-id="${String(data.id)}"]`
            );

        if (existing) {
            return false;
        }
    }


    const messageElement =
        document.createElement("div");

    const currentUser =
        chatConfig.username;


    messageElement.classList.add(
        "message"
    );


    if (data.username === currentUser) {

        messageElement.classList.add(
            "own"
        );
    }


    const content =
        document.createElement("div");

    content.classList.add(
        "message-content"
    );


    const username =
        document.createElement("div");

    username.classList.add(
        "username"
    );


    const avatar =
        createAvatar(
            data.username,
            data.avatar,
            "message-avatar"
        );


    const usernameText =
        document.createElement("span");

    usernameText.textContent =
        data.username;


    username.appendChild(avatar);
    username.appendChild(usernameText);


    const header =
        document.createElement("div");

    header.classList.add(
        "message-header"
    );

    header.appendChild(username);

    content.appendChild(header);


    // Цитата исходного сообщения для reply.
    if (data.reply_to) {

        const quote =
            createReplyQuote(
                data.reply_to
            );

        content.appendChild(quote);
    }


    if (data.message) {

        const text =
            document.createElement("div");

        text.classList.add("text");

        text.textContent =
            data.message;

        content.appendChild(text);
    }


    if (data.attachment) {

        const attachment =
            createAttachment(
                data.attachment,
                data.attachment_type,
                data.attachment_name
            );

        content.appendChild(attachment);
    }


    const time =
        document.createElement("div");

    time.classList.add("time");


    const date =
        new Date(data.created_at);


    time.textContent =
        date.toLocaleTimeString(
            [],
            {
                hour: "2-digit",
                minute: "2-digit",
            }
        );


    header.appendChild(time);


    messageElement.appendChild(
        content
    );


    const isOwn =
        messageElement.classList.contains(
            "own"
        );

    // Всплывающее меню "Реакция / Ответить" —
    // только на чужих сообщениях, при наведении.
    if (!isOwn) {

        const hoverMenu =
            createMessageHoverMenu(
                data
            );

        content.appendChild(hoverMenu);

        content.addEventListener(
            "mouseenter",
            function () {
                hoverMenu.hidden = false;
            }
        );

        content.addEventListener(
            "mouseleave",
            function () {
                hoverMenu.hidden = true;

                const picker =
                    hoverMenu.querySelector(
                        ".emoji-picker"
                    );

                if (picker) {
                    picker.hidden = true;
                }
            }
        );
    }


    // Реакции — в теле сообщения, в нижнем левом углу пузыря.
    const reactionsBar =
        createReactionsBar(
            data,
            currentUser,
            isOwn
        );

    content.appendChild(
        reactionsBar
    );

    // Если реакции есть — резервируем место внизу пузыря,
    // чтобы чипы не накладывались на текст.
    if (
        reactionsBar.querySelectorAll(
            ".reaction-chip"
        ).length
    ) {
        content.classList.add(
            "has-reactions"
        );
    }


    chatLog.appendChild(
        messageElement
    );


    messageElement.dataset.messageId =
        String(data.id);

    // Сохраняем исходные данные для построения
    // цитаты при ответе (reply).
    messageElement.__messageData =
        data;

    return true;
}


// ==================================================
// Message reactions & replies
// ==================================================

const EMOJI_SET = [
    "👍", "❤️", "😂", "😮", "😢", "🔥", "👏", "🎉",
];


let pendingReply = null;


function createReplyQuote(replyTo) {

    const quote =
        document.createElement("div");

    quote.classList.add(
        "reply-quote"
    );

    const header =
        document.createElement("div");

    header.classList.add(
        "reply-quote-header"
    );


    const name =
        document.createElement("span");

    name.classList.add(
        "reply-quote-name"
    );

    name.textContent =
        replyTo.username;

    header.appendChild(name);

    quote.appendChild(header);


    appendReplyQuoteMedia(
        quote,
        replyTo
    );


    if (replyTo.message) {

        const text =
            document.createElement("div");

        text.classList.add(
            "reply-quote-text"
        );

        text.textContent =
            replyTo.message;

        quote.appendChild(text);
    }


    quote.addEventListener(
        "click",
        function () {

            scrollToMessage(
                replyTo.id
            );
        }
    );


    return quote;
}


function scrollToMessage(messageId) {

    const target =
        findMessageElement(messageId);

    if (!target) {
        return;
    }

    target.scrollIntoView({
        behavior: "smooth",
        block: "center",
    });

    target.classList.add(
        "message-highlighted"
    );

    clearTimeout(
        target._highlightTimer
    );

    target._highlightTimer =
        setTimeout(
            function () {
                target.classList.remove(
                    "message-highlighted"
                );
            },
            2000
        );
}


function appendReplyQuoteMedia(quote, replyTo) {

    const type =
        replyTo.attachment_type;

    if (
        !type
        ||
        !replyTo.attachment
    ) {
        return;
    }

    const url =
        replyTo.attachment;

    if (
        type === "image"
        ||
        type === "video"
    ) {

        const link =
            document.createElement("a");

        link.href = url;

        link.target = "_blank";

        link.rel = "noopener";

        link.classList.add(
            "reply-quote-thumb-wrap"
        );

        const media =
            document.createElement(
                type === "image"
                    ? "img"
                    : "video"
            );

        media.src = url;

        media.loading = "lazy";

        media.classList.add(
            "reply-quote-thumb"
        );

        if (type === "image") {

            media.alt =
                replyTo.attachment_name
                || "Изображение";

        } else {

            media.preload = "metadata";

            media.muted = true;

            media.playsInline = true;
        }

        link.appendChild(media);

        quote.appendChild(link);

        return;
    }

    const label =
        document.createElement("div");

    label.classList.add(
        "reply-quote-attachment"
    );

    const typeIcon =
        type === "audio"
            ? "🎵"
            : "📎";

    label.textContent =
        typeIcon + " " + (
            replyTo.attachment_name
            || type
        );

    quote.appendChild(label);
}


function openReplyPreview(messageId, messageElement) {

    if (messageId === pendingReply) {
        cancelReplyPreview();
        return;
    }

    const messageData =
        getMessageData(
            messageId
        );

    pendingReply = messageId;

    renderReplyPreview(
        messageId,
        messageData
    );

    setInputPlaceholderReply();

    focusMessageInput();
}


function renderReplyPreview(messageId, messageData) {

    const preview =
        document.createElement("div");

    preview.classList.add(
        "reply-preview"
    );


    const cover =
        document.createElement("div");

    cover.classList.add(
        "reply-preview-block"
    );


    const label =
        document.createElement("span");

    label.classList.add(
        "reply-preview-label"
    );

    label.textContent = "Ответ на:";

    cover.appendChild(label);


    if (messageData) {

        const quote =
            createReplyQuote(
                messageData
            );

        cover.appendChild(quote);
    }
    else {

        const text =
            document.createElement("span");

        text.textContent =
            "#" + messageId;

        cover.appendChild(text);
    }


    const close =
        document.createElement("button");

    close.type = "button";

    close.classList.add(
        "reply-preview-close"
    );

    close.title = "Отменить ответ";

    close.setAttribute(
        "aria-label",
        "Отменить ответ"
    );

    close.textContent = "✕";

    close.addEventListener(
        "click",
        cancelReplyPreview
    );

    preview.appendChild(cover);
    preview.appendChild(close);


    const replyPreviewWrap =
        document.getElementById(
            "chat-reply-preview"
        );

    if (!replyPreviewWrap) {
        return;
    }

    replyPreviewWrap.innerHTML = "";
    replyPreviewWrap.appendChild(preview);

    replyPreviewWrap.hidden = false;
}


function cancelReplyPreview() {

    pendingReply = null;

    const replyPreviewWrap =
        document.getElementById(
            "chat-reply-preview"
        );

    if (!replyPreviewWrap) {
        return;
    }

    replyPreviewWrap.innerHTML = "";
    replyPreviewWrap.hidden = true;

    setInputPlaceholderDefault();
}


function setInputPlaceholderReply() {

    const input =
        document.getElementById(
            "chat-message-input"
        );

    if (!input) {
        return;
    }

    input.placeholder =
        "Введите ответ на сообщение...";
}


function setInputPlaceholderDefault() {

    const input =
        document.getElementById(
            "chat-message-input"
        );

    if (!input) {
        return;
    }

    input.placeholder =
        "Введите сообщение...";
}


function focusMessageInput() {

    const input =
        document.getElementById(
            "chat-message-input"
        );

    if (!input) {
        return;
    }

    input.focus();
}


function getMessageData(messageId) {

    const element =
        findMessageElement(messageId);

    if (!element) {
        return null;
    }

    return element.__messageData || null;
}


function createReactionsBar(data, currentUser, isOwn) {

    const bar =
        document.createElement("div");

    bar.classList.add(
        "message-reactions"
    );

    bar.dataset.interactive =
        isOwn ? "0" : "1";


    const reactions =
        data.reactions || [];


    reactions.forEach(function (reaction) {

        bar.appendChild(
            createReactionChip(
                reaction,
                data.id,
                currentUser,
                !isOwn
            )
        );
    });


    return bar;
}


function createMessageHoverMenu(data) {

    const messageId = data.id;

    const menu =
        document.createElement("div");

    menu.classList.add(
        "message-hover-menu"
    );

    menu.hidden = true;

    // Меню при наведении — только кнопки реакций.
    EMOJI_SET.forEach(function (emoji) {

        const button =
            document.createElement("button");

        button.type = "button";

        button.className =
            "emoji-option";

        button.textContent = emoji;

        button.title = emoji;

        button.addEventListener(
            "click",
            function () {

                sendReaction(
                    messageId,
                    emoji
                );
            }
        );

        menu.appendChild(button);
    });

    return menu;
}


async function openDirectMessage(username) {

    if (!username) {
        return;
    }

    try {

        const response =
            await apiRequest(
                chatConfig.directMessageUrl,
                {
                    method: "POST",
                    body: new URLSearchParams({
                        username: username,
                    }),
                }
            );

        const data =
            await response.json();

        if (
            data
            &&
            data.success
            &&
            data.url
        ) {
            window.location.href =
                data.url;
        }
        else if (
            data
            &&
            data.message
        ) {
            showToast(
                data.message,
                "error"
            );
        }
    }
    catch (error) {

        showToast(
            "Не удалось открыть личный чат.",
            "error"
        );
    }
}


function createReactionChip(
    reaction,
    messageId,
    currentUser,
    interactive
) {

    const chip =
        document.createElement(
            interactive
                ? "button"
                : "span"
        );

    if (interactive) {
        chip.type = "button";
    }

    chip.classList.add(
        "reaction-chip"
    );

    if (reaction.reacted_by_me) {

        chip.classList.add(
            "active"
        );
    }


    const emoji =
        document.createElement("span");

    emoji.classList.add(
        "reaction-emoji"
    );

    emoji.textContent =
        reaction.emoji;


    const count =
        document.createElement("span");

    count.classList.add(
        "reaction-count"
    );

    count.textContent =
        reaction.count;


    chip.appendChild(emoji);
    chip.appendChild(count);


    if (interactive) {

        chip.addEventListener(
            "click",
            function (event) {

                event.stopPropagation();

                sendReaction(
                    messageId,
                    reaction.emoji
                );
            }
        );
    }


    return chip;
}


function sendReaction(messageId, emoji) {

    if (
        !chatSocket
        ||
        chatSocket.readyState !== WebSocket.OPEN
    ) {

        showToast(
            "Соединение с чатом потеряно.",
            "error"
        );

        return;
    }

    chatSocket.send(
        JSON.stringify({
            type: "react",
            message_id: messageId,
            emoji: emoji,
        })
    );
}


function updateMessageReactions(messageId, reactions) {

    const messageElement =
        findMessageElement(messageId);

    if (!messageElement) {
        return;
    }

    const bar =
        messageElement.querySelector(
            ".message-reactions"
        );

    if (!bar) {
        return;
    }

    const currentUser =
        chatConfig.username;

    const interactive =
        bar.dataset.interactive !== "0";

    // Пересобираем чипы, сохраняя агрегатную truth и local state.
    // Запоминаем, на какие эмодзи текущий пользователь уже реагировал,
    // ДО удаления старых чипов (поле reacted_by_me в live-рассылке
    // отсутствует — его нужно восстановить локально).
    const myActiveEmojis =
        new Set();

    const oldChips =
        bar.querySelectorAll(
            ".reaction-chip"
        );

    oldChips.forEach(function (chip) {

        if (chip.classList.contains("active")) {

            const chipEmoji =
                chip.querySelector(
                    ".reaction-emoji"
                )?.textContent;

            if (chipEmoji) {
                myActiveEmojis.add(chipEmoji);
            }
        }

        chip.remove();
    });

    // Поле reacted_by_me в live-рассылке отсутствует,
    // поэтому обновляем его локально по текущему пользователю.
    const localReactions =
        reactions.map(function (reaction) {

            const copy = {
                ...reaction,
            };

            copy.reacted_by_me =
                myActiveEmojis.has(
                    reaction.emoji
                );

            return copy;
        });

    localReactions.forEach(function (reaction) {

        bar.appendChild(
            createReactionChip(
                reaction,
                messageId,
                currentUser,
                interactive
            )
        );
    });

    // Резервируем место внизу пузыря, если реакции появились.
    const content =
        messageElement.querySelector(
            ".message-content"
        );

    if (content) {

        content.classList.toggle(
            "has-reactions",
            bar.querySelectorAll(
                ".reaction-chip"
            ).length > 0
        );
    }
}


function findMessageElement(messageId) {

    if (!chatLog) {
        return null;
    }

    return chatLog.querySelector(
        `[data-message-id="${String(messageId)}"]`
    );
}


function createAttachment(
    url,
    type,
    name
) {

    const wrap =
        document.createElement("div");

    wrap.classList.add(
        "message-attachment"
    );


    if (type === "image") {

        const link =
            document.createElement("a");

        link.href = url;

        link.target = "_blank";

        link.rel = "noopener";


        const image =
            document.createElement("img");

        image.src = url;

        image.alt =
            name || "Изображение";

        image.loading = "lazy";

        link.appendChild(image);


        const mediaWrap =
            createMediaWrap();

        mediaWrap.appendChild(link);

        mediaWrap.appendChild(
            createDownloadIcon(
                url,
                name
            )
        );

        wrap.appendChild(mediaWrap);

    } else if (type === "video") {

        const video =
            document.createElement("video");

        video.src = url;

        video.controls = true;

        video.preload = "metadata";


        const mediaWrap =
            createMediaWrap();

        mediaWrap.appendChild(video);

        mediaWrap.appendChild(
            createDownloadIcon(
                url,
                name
            )
        );

        wrap.appendChild(mediaWrap);

    } else if (type === "audio") {

        const audio =
            document.createElement("audio");

        audio.src = url;

        audio.controls = true;

        audio.preload = "metadata";

        wrap.appendChild(audio);

        wrap.appendChild(
            createDownloadLink(
                url,
                name
            )
        );

    } else {

        const link =
            document.createElement("a");

        link.href = url;

        link.target = "_blank";

        link.rel = "noopener";

        link.download =
            name || "файл";

        link.classList.add(
            "message-attachment-link"
        );

        link.textContent =
            name || "Скачать файл";

        wrap.appendChild(link);
    }


    return wrap;
}


function createMediaWrap() {

    const mediaWrap =
        document.createElement("div");

    mediaWrap.classList.add(
        "attachment-media-wrap"
    );

    return mediaWrap;
}


function createDownloadIcon(
    url,
    name
) {

    const link =
        document.createElement("a");

    link.href = url;

    link.download =
        name || "файл";

    link.classList.add(
        "attachment-download-icon"
    );

    link.title = "Скачать";

    link.setAttribute(
        "aria-label",
        "Скачать"
    );

    const svg =
        document.createElementNS(
            "http://www.w3.org/2000/svg",
            "svg"
        );

    svg.setAttribute(
        "xmlns",
        "http://www.w3.org/2000/svg"
    );

    svg.setAttribute(
        "viewBox",
        "0 0 24 24"
    );

    svg.setAttribute(
        "width",
        "16"
    );

    svg.setAttribute(
        "height",
        "16"
    );

    svg.setAttribute(
        "fill",
        "none"
    );

    svg.setAttribute(
        "stroke",
        "currentColor"
    );

    svg.setAttribute(
        "stroke-width",
        "2"
    );

    svg.setAttribute(
        "stroke-linecap",
        "round"
    );

    svg.setAttribute(
        "stroke-linejoin",
        "round"
    );

    svg.setAttribute(
        "aria-hidden",
        "true"
    );

    const path =
        document.createElementNS(
            "http://www.w3.org/2000/svg",
            "path"
        );

    path.setAttribute(
        "d",
        "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"
    );

    svg.appendChild(path);

    const polyline =
        document.createElementNS(
            "http://www.w3.org/2000/svg",
            "polyline"
        );

    polyline.setAttribute(
        "points",
        "7 10 12 15 17 10"
    );

    svg.appendChild(polyline);

    const line =
        document.createElementNS(
            "http://www.w3.org/2000/svg",
            "line"
        );

    line.setAttribute(
        "x1",
        "12"
    );

    line.setAttribute(
        "y1",
        "15"
    );

    line.setAttribute(
        "x2",
        "12"
    );

    line.setAttribute(
        "y2",
        "3"
    );

    svg.appendChild(line);

    link.appendChild(svg);

    return link;
}


function createDownloadLink(
    url,
    name
) {

    const link =
        document.createElement("a");

    link.href = url;

    link.download =
        name || "файл";

    link.classList.add(
        "attachment-download"
    );

    link.textContent =
        "Скачать";

    return link;
}


function createAvatar(
    name,
    imageUrl,
    className
) {

    const avatar =
        document.createElement("span");

    avatar.classList.add(
        className
    );


    if (imageUrl) {

        const image =
            document.createElement("img");

        image.src =
            imageUrl;

        image.alt =
            `Аватар ${name}`;

        avatar.appendChild(image);

    } else {

        avatar.textContent =
            name
                .charAt(0)
                .toUpperCase();
    }


    return avatar;
}


function showSystemMessage(
    username,
    action
) {

    if (!chatLog) {
        return;
    }


    const element =
        document.createElement("div");

    element.classList.add(
        "system-message"
    );


    if (action === "join") {

        element.textContent =
            `🟢 ${username} вошёл в чат`;

    } else if (action === "leave") {

        element.textContent =
            `🔴 ${username} вышел из чата`;

    } else {

        return;
    }


    chatLog.appendChild(element);
}


function scrollToBottom(
    smooth = true
) {

    if (!chatLog) {
        return;
    }


    if (smooth) {

        chatLog.scrollTo({
            top: chatLog.scrollHeight,
            behavior: "smooth",
        });

    } else {

        chatLog.scrollTop =
            chatLog.scrollHeight;
    }
}


// ==================================================
// Send message
// ==================================================

function sendMessage() {

    const input =
        document.getElementById(
            "chat-message-input"
        );


    if (!input) {
        return;
    }


    const message =
        input.value.trim();


    if (!message) {
        return;
    }


    if (
        !chatSocket
        ||
        chatSocket.readyState !== WebSocket.OPEN
    ) {

        // Соединение переподключается — сообщение сохраняем
        // и отправим сразу после восстановления связи.
        if (shouldReconnect) {

            const offlinePayload =
                pendingReply
                    ? {
                        type: "comment",
                        text: message,
                        reply_to_id: pendingReply,
                    }
                    : { message };

            pendingMessages.push(
                offlinePayload
            );

            input.value = "";

            cancelReplyPreview();

            setInputPlaceholderDefault();

            updateInputMode();

            input.focus();

            return;
        }

        alert(
            "Соединение с чатом потеряно. " +
            "Перезагрузите страницу."
        );

        return;
    }


    let payload = {
        message,
    };


    // Если выбрано сообщение для ответа — прикрепляем reply.
    if (pendingReply) {

        payload = {
            type: "comment",
            text: message,
            reply_to_id: pendingReply,
        };
    }


    chatSocket.send(
        JSON.stringify(payload)
    );


    // Сбрасываем режим ответа (preview закрывается).
    cancelReplyPreview();

    // Возвращаем placeholder поля ввода.
    setInputPlaceholderDefault();

    input.value = "";

    updateInputMode();

    input.focus();
}


const messageSubmitButton =
    document.getElementById(
        "chat-message-submit"
    );


const messageInput =
    document.getElementById(
        "chat-message-input"
    );


if (messageSubmitButton) {

    messageSubmitButton.addEventListener(
        "click",
        sendMessage
    );
}


if (messageInput) {

    messageInput.addEventListener(
        "keydown",
        function (event) {

            if (
                event.key === "Enter"
                &&
                !event.shiftKey
            ) {

                event.preventDefault();

                sendMessage();
            }
        }
    );

    messageInput.addEventListener(
        "input",
        updateInputMode
    );
}


// ==================================================
// Emoji (вставка смайликов в сообщение)
// ==================================================

const EMOJI_GROUPS = [
    {
        label: "Смайлы",
        emojis: [
            "😀", "😁", "😂", "🤣", "😊", "😇", "🙂", "😉",
            "😍", "🥰", "😘", "😋", "😜", "🤪", "🤔", "🤗",
            "😎", "🥳", "😏", "😒", "😔", "😴", "🥺", "😢",
            "😭", "😅", "😳", "🙃", "🥱", "🤯", "😱", "😡",
            "🤬", "😷", "🤒", "🤢", "🤮", "🥶", "🫠",
        ],
    },
    {
        label: "Жесты",
        emojis: [
            "👍", "👎", "👌", "✌️", "🤞", "🤟", "🤘", "🤙",
            "👈", "👉", "👆", "👇", "☝️", "👋", "🤚", "✋",
            "🖖", "👏", "🙌", "👐", "🤲", "🤝", "🙏", "💪",
            "✊", "👊", "🤛", "🤜",
        ],
    },
    {
        label: "Сердца",
        emojis: [
            "❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍",
            "🤎", "💔", "❣️", "💕", "💞", "💓", "💗", "💖",
            "💘", "💝", "💟",
        ],
    },
    {
        label: "Животные",
        emojis: [
            "🐶", "🐱", "🐭", "🐹", "🐰", "🦊", "🐻", "🐼",
            "🐨", "🐯", "🦁", "🐮", "🐷", "🐸", "🐵", "🙈",
            "🙉", "🙊", "🐔", "🐧", "🐦", "🦄", "🐝", "🐢",
            "🐍", "🦋", "🐙", "🦀", "🐬", "🐳", "🐠", "🦈",
        ],
    },
    {
        label: "Еда и напитки",
        emojis: [
            "🍏", "🍎", "🍐", "🍊", "🍋", "🍌", "🍉", "🍇",
            "🍓", "🍒", "🍑", "🥭", "🍍", "🥥", "🥝", "🍅",
            "🥑", "🥦", "🌽", "🍞", "🧀", "🍗", "🍔", "🍟",
            "🍕", "🌮", "🌯", "🥗", "🍿", "🧁", "🍰", "🍦",
            "🍩", "🍪", "☕", "🍵", "🧃", "🍺", "🍻", "🥂",
        ],
    },
    {
        label: "Активности",
        emojis: [
            "⚽", "🏀", "🏈", "⚾", "🎾", "🏐", "🎱", "🏓",
            "🏸", "🎯", "🎮", "🎲", "🧩", "🎨", "🎭", "🎬",
            "🎵", "🎧", "🎤", "🎸", "🎹", "🥁", "🎺",
        ],
    },
    {
        label: "Путешествия",
        emojis: [
            "🚗", "🚕", "🚙", "🚌", "🏎️", "🚓", "🚑", "🚒",
            "🚜", "🏍️", "🛴", "🚲", "✈️", "🚀", "🛸", "🚁",
            "⛵", "🚤", "🛳️",
        ],
    },
    {
        label: "Предметы",
        emojis: [
            "📱", "💻", "🖥️", "🖨️", "📷", "🎥", "💡", "🔥",
            "⭐", "🌟", "☀️", "🌙", "🌈", "⚡", "❄️", "💎",
            "📚", "✏️", "✂️", "🔑", "🔔",
        ],
    },
];


const chatEmojiWrap =
    document.getElementById(
        "chat-emoji-wrap"
    );


const chatEmojiButton =
    document.getElementById(
        "chat-emoji-button"
    );


const chatEmojiPanel =
    document.getElementById(
        "chat-emoji-panel"
    );


let emojiPickerOpen = false;


// Собираем панель смайликов из групп.
function buildEmojiPicker() {

    if (!chatEmojiPanel) {
        return;
    }

    const fragment =
        document.createDocumentFragment();

    for (const group of EMOJI_GROUPS) {

        const groupEl =
            document.createElement("div");

        groupEl.className =
            "chat-emoji-group";

        const titleEl =
            document.createElement("div");

        titleEl.className =
            "chat-emoji-group-title";

        titleEl.textContent =
            group.label;

        groupEl.appendChild(
            titleEl
        );

        const gridEl =
            document.createElement("div");

        gridEl.className =
            "chat-emoji-grid";

        for (const emoji of group.emojis) {

            const itemEl =
                document.createElement("button");

            itemEl.type = "button";

            itemEl.className =
                "chat-emoji-item";

            itemEl.textContent =
                emoji;

            itemEl.title =
                emoji;

            itemEl.addEventListener(
                "click",
                function () {
                    insertEmoji(emoji);
                }
            );

            gridEl.appendChild(
                itemEl
            );
        }

        groupEl.appendChild(
            gridEl
        );

        fragment.appendChild(
            groupEl
        );
    }

    chatEmojiPanel.appendChild(
        fragment
    );
}


function setEmojiPickerOpen(open) {

    emojiPickerOpen = open;

    if (chatEmojiPanel) {
        chatEmojiPanel.hidden =
            !open;
    }

    if (chatEmojiButton) {
        chatEmojiButton.classList.toggle(
            "active",
            open
        );

        chatEmojiButton.setAttribute(
            "aria-expanded",
            open ? "true" : "false"
        );
    }
}


// Вставляет выбранный смайлик в место курсора.
function insertEmoji(emoji) {

    if (!messageInput) {
        return;
    }

    const start =
        messageInput.selectionStart ?? messageInput.value.length;

    const end =
        messageInput.selectionEnd ?? start;

    const value =
        messageInput.value;

    messageInput.value =
        value.slice(0, start) +
        emoji +
        value.slice(end);

    const caret =
        start + emoji.length;

    messageInput.setSelectionRange(
        caret,
        caret
    );

    messageInput.focus();

    // Обновляем кнопки («микрофон»/«отправить»).
    messageInput.dispatchEvent(
        new Event("input")
    );
}


if (chatEmojiButton) {

    chatEmojiButton.addEventListener(
        "click",
        function (event) {

            event.stopPropagation();

            setEmojiPickerOpen(
                !emojiPickerOpen
            );
        }
    );
}


// Закрываем панель по клику вне её.
document.addEventListener(
    "click",
    function (event) {

        if (
            emojiPickerOpen
            &&
            chatEmojiWrap
            &&
            !chatEmojiWrap.contains(
                event.target
            )
        ) {
            setEmojiPickerOpen(false);
        }
    }
);


// Закрываем панель по Escape.
document.addEventListener(
    "keydown",
    function (event) {

        if (
            event.key === "Escape"
            &&
            emojiPickerOpen
        ) {
            setEmojiPickerOpen(false);
        }
    }
);


buildEmojiPicker();


// ==================================================
// Message actions (контекстное меню сообщения)
// ==================================================

const chatSelectionBar =
    document.getElementById(
        "chat-selection-bar"
    );


const chatSelectionCount =
    document.getElementById(
        "chat-selection-count"
    );


const chatSelectionCopy =
    document.getElementById(
        "chat-selection-copy"
    );


const chatSelectionForward =
    document.getElementById(
        "chat-selection-forward"
    );


const chatSelectionDelete =
    document.getElementById(
        "chat-selection-delete"
    );


const chatSelectionCancel =
    document.getElementById(
        "chat-selection-cancel"
    );


let contextMenu = null;
let contextMenuTarget = null;
let contextMenuData = null;

let selectionMode = false;
let selectedMessageIds = new Set();

let forwardMessageIds = [];


const contextMenuItems = [
    {
        id: "reply",
        icon: "↩️",
        label: "Ответить",
        title: "Ответить на сообщение",
        show: function (data) {
            return (
                data.username !== chatConfig.username
            );
        },
        handler: replyToMessage,
    },
    {
        id: "message",
        icon: "💬",
        label: "Сообщение",
        title: "Написать личное сообщение",
        show: function (data) {
            return (
                data.username !== chatConfig.username
            );
        },
        handler: directMessageAction,
    },
    {
        id: "edit",
        icon: "✏️",
        label: "Редактировать",
        title: "Редактировать сообщение",
        show: function (data) {
            return (
                data.username === chatConfig.username
            );
        },
        handler: startEditMessage,
    },
    {
        id: "copy",
        icon: "📋",
        label: "Копировать",
        title: "Копировать сообщение",
        show: function () {
            return true;
        },
        handler: copyMessage,
    },
    {
        id: "forward",
        icon: "➡️",
        label: "Переслать",
        title: "Переслать в другую комнату",
        show: function () {
            return (
                Array.isArray(chatConfig.forwardRooms)
                &&
                chatConfig.forwardRooms.length > 0
            );
        },
        handler: openForwardModal,
    },
    {
        id: "delete",
        icon: "🗑️",
        label: "Удалить",
        title: "Удалить сообщение",
        show: function (data) {
            return (
                data.username === chatConfig.username
                ||
                chatConfig.isRoomOwner
            );
        },
        handler: deleteMessage,
    },
    {
        id: "select",
        icon: "✅",
        label: "Выбрать",
        title: "Режим выбора сообщений",
        show: function () {
            return true;
        },
        handler: function () {
            const messageId =
                contextMenuData
                    ? contextMenuData.id
                    : null;

            enterSelectionMode();

            if (messageId) {
                setMessageSelected(
                    messageId,
                    findMessageElement(messageId),
                    true
                );
            }
        },
    },
];


// Строим единое контекстное меню (одно на весь чат,
// позиционируется у курсора).
function createContextMenu() {

    if (
        contextMenu
        ||
        !document.body
    ) {
        return;
    }

    contextMenu =
        document.createElement("div");

    contextMenu.className =
        "message-context-menu";

    contextMenu.hidden = true;

    contextMenu.setAttribute(
        "role",
        "menu"
    );

    document.body.appendChild(
        contextMenu
    );
}


// Наполняем меню доступными для этого сообщения пунктами.
function buildContextMenu() {

    if (!contextMenu) {
        return;
    }

    contextMenu.innerHTML = "";

    for (const item of contextMenuItems) {

        if (
            contextMenuData
            &&
            !item.show(contextMenuData)
        ) {
            continue;
        }

        const button =
            document.createElement("button");

        button.type = "button";

        button.className =
            "context-menu-btn";

        button.dataset.actionId =
            item.id;

        button.title =
            item.title;

        const icon =
            document.createElement("span");

        icon.className =
            "context-menu-icon";

        icon.textContent =
            item.icon;

        const label =
            document.createElement("span");

        label.textContent =
            item.label;

        button.appendChild(icon);
        button.appendChild(label);

        button.addEventListener(
            "click",
            item.handler
        );

        contextMenu.appendChild(
            button
        );
    }
}


function openContextMenu(event, messageElement) {

    closeContextMenu();

    createContextMenu();

    const data =
        messageElement.__messageData;

    if (!contextMenu || !data) {
        return;
    }

    contextMenuTarget = messageElement;
    contextMenuData = data;

    buildContextMenu();

    if (
        !contextMenu.querySelector(
            ".context-menu-btn"
        )
    ) {
        return;
    }

    // Показываем меню без отрисовки, чтобы замерить реальные размеры
    // (в состоянии display:none offsetWidth/offsetHeight равны 0).
    contextMenu.style.visibility = "hidden";
    contextMenu.hidden = false;

    const menuWidth =
        contextMenu.offsetWidth;

    const menuHeight =
        contextMenu.offsetHeight;

    const margin = 8;

    // Ограничиваем меню границами области чата.
    let minLeft = margin;
    let minTop = margin;
    let maxRight = window.innerWidth - margin;
    let maxBottom = window.innerHeight - margin;

    if (chatLog) {

        const bounds =
            chatLog.getBoundingClientRect();

        if (menuHeight <= bounds.height - margin * 2) {
            minTop = bounds.top + margin;
            maxBottom = bounds.bottom - margin;
        }

        if (menuWidth <= bounds.width - margin * 2) {
            minLeft = bounds.left + margin;
            maxRight = bounds.right - margin;
        }
    }

    let left = event.clientX;
    let top = event.clientY;

    if (left + menuWidth > maxRight) {
        left = maxRight - menuWidth;
    }

    if (top + menuHeight > maxBottom) {
        top = maxBottom - menuHeight;
    }

    if (left < minLeft) {
        left = minLeft;
    }

    if (top < minTop) {
        top = minTop;
    }

    contextMenu.style.left =
        left + "px";

    contextMenu.style.top =
        top + "px";

    contextMenu.style.visibility = "";
    contextMenu.hidden = false;
}


function closeContextMenu() {

    if (contextMenu) {
        contextMenu.hidden = true;
    }

    contextMenuTarget = null;
    contextMenuData = null;
}


if (chatLog) {

    chatLog.addEventListener(
        "contextmenu",
        function (event) {

            const content =
                event.target.closest(
                    ".message-content"
                );

            if (!content) {
                return;
            }

            const messageElement =
                content.closest(".message");

            if (!messageElement) {
                return;
            }

            // Не мешаем системному меню на ссылках/кнопках.
            if (
                event.target.closest(
                    "a,button,input,textarea"
                )
            ) {
                return;
            }

            event.preventDefault();

            openContextMenu(
                event,
                messageElement
            );
        }
    );
}


document.addEventListener(
    "click",
    closeContextMenu
);


if (chatLog) {
    chatLog.addEventListener(
        "scroll",
        closeContextMenu
    );
}


window.addEventListener(
    "resize",
    closeContextMenu
);


document.addEventListener(
    "keydown",
    function (event) {

        if (event.key !== "Escape") {
            return;
        }

        if (selectionMode) {
            exitSelectionMode();
        }

        closeContextMenu();
    }
);


function copyTextToClipboard(text) {

    if (
        navigator.clipboard
        &&
        window.isSecureContext
    ) {
        return navigator.clipboard.writeText(text);
    }

    return new Promise(
        function (resolve, reject) {

            const textarea =
                document.createElement("textarea");

            textarea.value = text;

            textarea.setAttribute(
                "readonly",
                ""
            );

            textarea.style.position =
                "fixed";

            textarea.style.opacity =
                "0";

            document.body.appendChild(
                textarea
            );

            textarea.select();

            try {
                document.execCommand("copy");
                resolve();
            }
            catch (error) {
                reject(error);
            }
            finally {
                document.body.removeChild(
                    textarea
                );
            }
        }
    );
}


async function copyMessage() {

    const data = contextMenuData;

    closeContextMenu();

    if (!data) {
        return;
    }

    let text = data.message || "";

    if (!text && data.attachment) {
        text = data.attachment;
    }

    if (!text) {
        return;
    }

    try {
        await copyTextToClipboard(text);
        showToast(
            "Скопировано.",
            "ok"
        );
    }
    catch (error) {
        showToast(
            "Не удалось скопировать.",
            "error"
        );
    }
}


function replyToMessage() {

    const messageId =
        contextMenuData
            ? contextMenuData.id
            : null;

    closeContextMenu();

    if (!messageId) {
        return;
    }

    const messageElement =
        findMessageElement(messageId);

    if (messageElement) {
        openReplyPreview(
            messageId,
            messageElement
        );
    }
}


function directMessageAction() {

    const username =
        contextMenuData
            ? contextMenuData.username
            : null;

    closeContextMenu();

    if (username) {
        openDirectMessage(username);
    }
}


// Редактирование: заменяем текст сообщения на inline-поле.
function startEditMessage() {

    const messageId =
        contextMenuData
            ? contextMenuData.id
            : null;

    closeContextMenu();

    const messageElement =
        findMessageElement(messageId);

    if (
        !messageElement
        ||
        messageElement.querySelector(
            ".message-edit-wrap"
        )
    ) {
        return;
    }

    const data =
        messageElement.__messageData;

    const textDiv =
        messageElement.querySelector(
            ".text"
        );

    const wrap =
        document.createElement("div");

    wrap.className =
        "message-edit-wrap";

    const input =
        document.createElement("input");

    input.type = "text";

    input.className =
        "message-edit-input";

    input.value = data.message || "";

    input.maxLength = 1000;

    const actions =
        document.createElement("div");

    actions.className =
        "message-edit-actions";

    const saveButton =
        document.createElement("button");

    saveButton.type = "button";

    saveButton.className =
        "message-edit-save";

    saveButton.textContent =
        "Сохранить";

    const cancelButton =
        document.createElement("button");

    cancelButton.type = "button";

    cancelButton.className =
        "message-edit-cancel";

    cancelButton.textContent =
        "Отмена";

    actions.appendChild(saveButton);
    actions.appendChild(cancelButton);

    wrap.appendChild(input);
    wrap.appendChild(actions);

    if (textDiv) {
        textDiv.style.display = "none";

        textDiv.parentNode.insertBefore(
            wrap,
            textDiv
        );
    }
    else {
        const content =
            messageElement.querySelector(
                ".message-content"
            );

        if (content) {
            content.appendChild(wrap);
        }
    }

    messageElement.classList.add(
        "editing"
    );

    const finishEdit = function () {

        messageElement.classList.remove(
            "editing"
        );

        wrap.remove();

        if (textDiv) {
            textDiv.style.display = "";
        }
    };

    cancelButton.addEventListener(
        "click",
        finishEdit
    );

    saveButton.addEventListener(
        "click",
        async function () {

            await saveEditedMessage(
                messageId,
                input.value
            );

            finishEdit();
        }
    );

    input.addEventListener(
        "keydown",
        async function (event) {

            if (
                event.key === "Enter"
                &&
                !event.shiftKey
            ) {
                event.preventDefault();

                await saveEditedMessage(
                    messageId,
                    input.value
                );

                finishEdit();
            }
            else if (event.key === "Escape") {
                finishEdit();
            }
        }
    );

    input.focus();
    input.select();
}


async function saveEditedMessage(messageId, rawText) {

    const text =
        (rawText || "").trim();

    if (!text) {
        showToast(
            "Сообщение не может быть пустым.",
            "error"
        );

        return;
    }

    const url =
        chatConfig.editMessageUrlTemplate.replace(
            "0",
            String(messageId)
        );

    try {

        const response =
            await apiRequest(
                url,
                {
                    method: "POST",
                    body: new URLSearchParams({
                        text: text,
                    }),
                }
            );

        const data =
            await response.json();

        if (
            data.success
            &&
            data.message
        ) {
            updateMessage(data.message);
        }
        else {
            showToast(
                data.error
                ||
                "Не удалось изменить сообщение.",
                "error"
            );
        }
    }
    catch (error) {
        showToast(
            "Не удалось изменить сообщение.",
            "error"
        );
    }
}


// Обновляет содержимое уже отрисованного сообщения
// (в ответ на message_updated по WebSocket или ответ сервера).
function updateMessage(data) {

    const messageElement =
        findMessageElement(data.id);

    if (!messageElement) {
        return;
    }

    // Закрываем inline-редактирование, если оно открыто.
    const editWrap =
        messageElement.querySelector(
            ".message-edit-wrap"
        );

    if (editWrap) {
        editWrap.remove();
    }

    messageElement.classList.remove(
        "editing"
    );

    const oldText =
        messageElement.querySelector(
            ".text"
        );

    if (oldText) {
        oldText.style.display = "";
        oldText.textContent = data.message || "";
    }
    else if (data.message) {

        const text =
            document.createElement("div");

        text.classList.add("text");

        text.textContent = data.message;

        const content =
            messageElement.querySelector(
                ".message-content"
            );

        if (content) {
            content.insertBefore(
                text,
                messageElement.querySelector(
                    ".reactions-bar"
                )
            );
        }
    }

    // Маркер «изменено».
    let editedMark =
        messageElement.querySelector(
            ".message-edited"
        );

    if (data.edited_at) {

        if (!editedMark) {

            editedMark =
                document.createElement("span");

            editedMark.className =
                "message-edited";

            editedMark.textContent =
                "изменено";

            const textEl =
                messageElement.querySelector(
                    ".text"
                )
                ||
                messageElement.querySelector(
                    ".message-edit-wrap"
                );

            if (
                textEl
                &&
                textEl.parentNode
            ) {
                textEl.parentNode.insertBefore(
                    editedMark,
                    textEl.nextSibling
                );
            }
        }
    }
    else if (editedMark) {
        editedMark.remove();
    }

    messageElement.__messageData =
        data;
}


function removeMessageElement(messageId) {

    const messageElement =
        findMessageElement(messageId);

    if (messageElement) {
        messageElement.remove();
    }

    if (selectedMessageIds.has(messageId)) {
        selectedMessageIds.delete(messageId);
        updateSelectionCount();
    }
}


function deleteMessage() {

    const messageId =
        contextMenuData
            ? contextMenuData.id
            : null;

    closeContextMenu();

    if (!messageId) {
        return;
    }

    openConfirmDelete(
        [messageId]
    );
}


// Ожидающее удаление сообщений (подтверждается в модале).
let pendingDeleteIds = null;

const confirmDeleteModal =
    document.getElementById(
        "confirm-delete-modal"
    );

const confirmDeleteMessage =
    document.getElementById(
        "confirm-delete-message"
    );


function openConfirmDelete(ids) {

    pendingDeleteIds = ids;

    const count = ids.length;

    if (confirmDeleteMessage) {

        let text;

        if (count === 1) {
            text =
                "Вы уверены, что хотите удалить "
                + "это сообщение?";
        }
        else if (count < 5) {
            text =
                "Вы уверены, что хотите удалить "
                + count
                + " сообщения?";
        }
        else {
            text =
                "Вы уверены, что хотите удалить "
                + count
                + " сообщений?";
        }

        confirmDeleteMessage.textContent =
            text;
    }

    openModal(confirmDeleteModal);
}


// Массовое удаление подтверждённых сообщений.
async function deleteMessages(ids) {

    let lastError = null;

    for (const messageId of ids) {

        const url =
            chatConfig.deleteMessageUrlTemplate.replace(
                "0",
                String(messageId)
            );

        try {
            const response =
                await apiRequest(
                    url,
                    { method: "POST" }
                );

            const data =
                await response
                    .json()
                    .catch(
                        function () {
                            return null;
                        }
                    );

            if (data && data.success) {
                removeMessageElement(
                    messageId
                );
            }
            else {
                lastError =
                    (data && data.error)
                    ||
                    "Не удалось удалить сообщение.";
            }
        }
        catch (error) {
            lastError =
                "Не удалось удалить сообщение.";
        }
    }

    if (lastError) {
        showToast(
            lastError,
            "error"
        );
    }
    else {
        showToast(
            "Удалено.",
            "ok"
        );
    }
}


const confirmDeleteForm =
    document.getElementById(
        "confirm-delete-form"
    );


if (confirmDeleteForm) {

    confirmDeleteForm.addEventListener(
        "submit",
        async function (event) {

            event.preventDefault();

            if (
                !confirmDeleteModal
                ||
                confirmDeleteModal.classList.contains(
                    "hidden"
                )
            ) {
                return;
            }

            const ids = pendingDeleteIds;

            pendingDeleteIds = null;

            closeModal(confirmDeleteModal);

            exitSelectionMode();

            if (
                !ids
                ||
                !ids.length
            ) {
                return;
            }

            await deleteMessages(ids);
        }
    );
}


// Пересылка сообщения в другую комнату.
function openForwardModal() {

    const modal =
        document.getElementById(
            "forward-message-modal"
        );

    const select =
        document.getElementById(
            "forward-target-room"
        );

    const errorEl =
        document.getElementById(
            "forward-message-error"
        );

    // Если вызван из контекстного меню — пересылаем одно сообщение.
    if (contextMenuData) {
        forwardMessageIds =
            [contextMenuData.id];
    }

    closeContextMenu();

    if (!modal || !select) {
        return;
    }

    const rooms =
        chatConfig.forwardRooms || [];

    if (!rooms.length) {
        showToast(
            "Нет комнат для пересылки.",
            "error"
        );

        return;
    }

    select.innerHTML = "";

    for (const room of rooms) {

        const option =
            document.createElement("option");

        option.value =
            String(room.id);

        option.textContent =
            room.name;

        select.appendChild(
            option
        );
    }

    if (errorEl) {
        errorEl.classList.add("hidden");
    }

    openModal(modal);
}


const forwardMessageForm =
    document.getElementById(
        "forward-message-form"
    );


if (forwardMessageForm) {

    forwardMessageForm.addEventListener(
        "submit",
        async function (event) {

            event.preventDefault();

            const select =
                document.getElementById(
                    "forward-target-room"
                );

            const errorEl =
                document.getElementById(
                    "forward-message-error"
                );

            const targetRoomId =
                select
                    ? select.value
                    : "";

            if (!targetRoomId) {

                if (errorEl) {
                    errorEl.textContent =
                        "Выберите комнату.";

                    errorEl.classList.remove(
                        "hidden"
                    );
                }

                return;
            }

            const ids =
                forwardMessageIds;

            let lastError =
                null;

            for (const messageId of ids) {

                const url =
                    chatConfig.forwardMessageUrlTemplate.replace(
                        "0",
                        String(messageId)
                    );

                try {

                    const response =
                        await apiRequest(
                            url,
                            {
                                method: "POST",
                                body: new URLSearchParams({
                                    target_room_id: targetRoomId,
                                }),
                            }
                        );

                    const data =
                        await response.json();

                    if (!data.success) {
                        lastError =
                            data.error
                            ||
                            "Не удалось переслать сообщение.";
                    }
                }
                catch (error) {
                    lastError =
                        "Не удалось переслать сообщение.";
                }
            }

            closeModal(
                document.getElementById(
                    "forward-message-modal"
                )
            );

            forwardMessageIds = [];

            if (lastError) {
                showToast(
                    lastError,
                    "error"
                );
            }
            else {
                const count =
                    ids.length;

                const words =
                    count === 1
                        ? "Сообщение переслано."
                        : count < 5
                            ? "Сообщения пересланы."
                            : "Сообщений переслано.";

                showToast(
                    words,
                    "ok"
                );
            }
        }
    );
}


// Режим выбора сообщений.
function enterSelectionMode() {

    selectionMode = true;

    selectedMessageIds = new Set();

    if (chatLog) {
        chatLog.classList.add(
            "selection-mode"
        );
    }

    if (chatSelectionBar) {
        chatSelectionBar.hidden = false;
    }

    updateSelectionCount();

    closeContextMenu();
}


function exitSelectionMode() {

    selectionMode = false;

    selectedMessageIds = new Set();

    if (chatLog) {
        chatLog.classList.remove(
            "selection-mode"
        );

        chatLog
            .querySelectorAll(
                ".message.selected"
            )
            .forEach(
                function (element) {
                    element.classList.remove(
                        "selected"
                    );
                }
            );
    }

    if (chatSelectionBar) {
        chatSelectionBar.hidden = true;
    }

    updateSelectionCount();
}


function isMessageSelected(messageId) {
    return selectedMessageIds.has(messageId);
}


function setMessageSelected(messageId, messageElement, selected) {

    if (selected) {
        selectedMessageIds.add(messageId);
    }
    else {
        selectedMessageIds.delete(messageId);
    }

    if (messageElement) {
        messageElement.classList.toggle(
            "selected",
            selected
        );
    }

    updateSelectionCount();

    // Сняли выделение со всех сообщений — выходим из режима.
    if (
        selectionMode
        &&
        selectedMessageIds.size === 0
    ) {
        exitSelectionMode();
    }
}


function toggleMessageSelection(messageId, messageElement) {

    setMessageSelected(
        messageId,
        messageElement,
        !isMessageSelected(messageId)
    );
}


function updateSelectionCount() {

    if (chatSelectionCount) {
        chatSelectionCount.textContent =
            String(selectedMessageIds.size);
    }

    if (chatSelectionBar) {
        chatSelectionBar.hidden =
            !selectionMode
            ||
            selectedMessageIds.size === 0;
    }

    // Удаление видно, только если ВЫБРАНЫ ИСКЛЮЧИТЕЛЬНО СВОИ сообщения.
    if (chatSelectionDelete) {

        let allOwn = true;

        selectedMessageIds.forEach(
            function (messageId) {

                const element =
                    findMessageElement(messageId);

                const data =
                    element
                        ? element.__messageData
                        : null;

                if (
                    data
                    &&
                    data.username !== chatConfig.username
                ) {
                    allOwn = false;
                }
            }
        );

        chatSelectionDelete.hidden =
            !allOwn
            ||
            selectedMessageIds.size === 0;
    }
}


if (chatLog) {

    chatLog.addEventListener(
        "click",
        function (event) {

            if (!selectionMode) {
                return;
            }

            const content =
                event.target.closest(
                    ".message-content"
                );

            if (!content) {
                return;
            }

            if (
                event.target.closest(
                    "a,button,input,textarea"
                )
            ) {
                return;
            }

            const messageElement =
                content.closest(".message");

            if (!messageElement) {
                return;
            }

            toggleMessageSelection(
                messageElement.dataset.messageId,
                messageElement
            );
        }
    );
}


if (chatSelectionCopy) {

    chatSelectionCopy.addEventListener(
        "click",
        async function () {

            const texts = [];

            selectedMessageIds.forEach(
                function (messageId) {

                    const messageElement =
                        findMessageElement(messageId);

                    const data =
                        messageElement
                            ? messageElement.__messageData
                            : null;

                    if (data && data.message) {
                        texts.push(
                            data.username + ": " + data.message
                        );
                    }
                }
            );

            if (!texts.length) {
                showToast(
                    "Нет текстовых сообщений для копирования.",
                    "error"
                );

                return;
            }

            try {
                await copyTextToClipboard(
                    texts.join("\n")
                );

                showToast(
                    "Скопировано.",
                    "ok"
                );
            }
            catch (error) {
                showToast(
                    "Не удалось скопировать.",
                    "error"
                );
            }
        }
    );
}


if (chatSelectionForward) {

    chatSelectionForward.addEventListener(
        "click",
        function () {

            if (!selectedMessageIds.size) {
                return;
            }

            forwardMessageIds =
                Array.from(
                    selectedMessageIds
                );

            openForwardModal();
        }
    );
}


if (chatSelectionDelete) {

    chatSelectionDelete.addEventListener(
        "click",
        function () {

            if (!selectedMessageIds.size) {
                return;
            }

            openConfirmDelete(
                Array.from(
                    selectedMessageIds
                )
            );
        }
    );
}


if (chatSelectionCancel) {

    chatSelectionCancel.addEventListener(
        "click",
        exitSelectionMode
    );
}


// ==================================================
// Voice messages (запись голосовых сообщений)
// ==================================================

const RECORD_HOLD_MS =
    1500;

const MAX_RECORD_MS =
    5 * 60 * 1000;

const chatRecordButton =
    document.getElementById(
        "chat-record-button"
    );


const chatRecordingBar =
    document.getElementById(
        "chat-recording-bar"
    );


const chatRecordingTime =
    document.getElementById(
        "chat-recording-time"
    );


let mediaRecorder = null;
let recordedChunks = [];
let recordHoldTimer = null;
let recordHoldActive = false;
let recordStartTime = 0;
let recordTimerInterval = null;
let isRecording = false;


// Переключение кнопок: пусто — микрофон, есть текст — отправить.
function updateInputMode() {

    const hasText =
        !!(
            messageInput
            &&
            messageInput.value.trim()
        );

    if (messageSubmitButton) {
        messageSubmitButton.hidden =
            !hasText;
    }

    if (chatRecordButton) {
        chatRecordButton.hidden =
            hasText;
    }
}


function cancelRecordHold() {

    if (recordHoldTimer) {

        clearTimeout(recordHoldTimer);

        recordHoldTimer = null;
    }

    recordHoldActive = false;

    chatRecordButton?.classList.remove(
        "holding"
    );
}


function beginRecordHold() {

    if (
        mediaBusy
        ||
        isRecording
        ||
        !chatRecordButton
        ||
        chatRecordButton.hidden
    ) {
        return;
    }

    cancelRecordHold();

    recordHoldActive = true;

    chatRecordButton.classList.add(
        "holding"
    );

    recordHoldTimer =
        setTimeout(
            startRecording,
            RECORD_HOLD_MS
        );
}


async function startRecording() {

    recordHoldTimer = null;

    if (
        !navigator.mediaDevices
        ||
        !navigator.mediaDevices.getUserMedia
        ||
        !window.MediaRecorder
    ) {

        cancelRecordHold();

        showToast(
            "Запись аудио недоступна в этом браузере.",
            "error"
        );

        return;
    }

    try {

        const stream =
            await navigator
                .mediaDevices
                .getUserMedia({
                    audio: true,
                });

        // Пока ждали разрешение микрофона —
        // кнопку уже могли отпустить.
        if (!recordHoldActive) {

            stream
                .getTracks()
                .forEach(
                    function (track) {
                        track.stop();
                    }
                );

            return;
        }

        recordHoldActive = false;

        chatRecordButton?.classList.remove(
            "holding"
        );

        const mimeType =
            pickAudioMimeType();

        mediaRecorder =
            new MediaRecorder(
                stream,
                mimeType
                    ? { mimeType }
                    : undefined
            );

        recordedChunks = [];

        mediaRecorder.ondataavailable =
            function (event) {

                if (event.data.size > 0) {

                    recordedChunks.push(
                        event.data
                    );
                }
            };

        mediaRecorder.onstop =
            finishRecording;

        mediaRecorder.start();

        isRecording = true;

        recordStartTime =
            Date.now();

        setRecordingUi(true);

        recordTimerInterval =
            setInterval(
                updateRecordingTime,
                500
            );

        updateRecordingTime();

    } catch (error) {

        cancelRecordHold();

        console.error(
            "Mic access error:",
            error
        );

        showToast(
            "Не удалось получить доступ к микрофону.",
            "error"
        );
    }
}


function pickAudioMimeType() {

    const candidates = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
        "audio/ogg;codecs=opus",
    ];

    for (const type of candidates) {

        if (
            MediaRecorder.isTypeSupported(
                type
            )
        ) {
            return type;
        }
    }

    return "";
}


function releaseRecordButton() {

    if (isRecording) {

        stopRecording();

    } else {

        cancelRecordHold();
    }
}


function stopRecording() {

    if (
        mediaRecorder
        &&
        mediaRecorder.state !== "inactive"
    ) {

        mediaRecorder.stop();
    }
}


function finishRecording() {

    isRecording = false;

    clearInterval(recordTimerInterval);

    recordTimerInterval = null;

    const stream =
        mediaRecorder
            ? mediaRecorder.stream
            : null;

    if (stream) {

        stream
            .getTracks()
            .forEach(
                function (track) {
                    track.stop();
                }
            );
    }

    setRecordingUi(false);

    if (recordedChunks.length === 0) {

        showToast(
            "Слишком короткое аудио.",
            "error"
        );

        return;
    }

    const blob =
        new Blob(
            recordedChunks,
            {
                type:
                    mediaRecorder
                        ? mediaRecorder.mimeType
                        : "audio/webm",
            }
        );

    mediaRecorder = null;

    recordedChunks = [];

    sendRecordedAudio(blob);
}


function sendRecordedAudio(blob) {

    if (blob.size < 200) {

        showToast(
            "Слишком короткое аудио.",
            "error"
        );

        return;
    }

    const file =
        blobToAudioFile(blob);

    setMediaBusy(true);

    uploadMediaFile(
        file,
        ""
    )
        .then(
            function (ok) {

                setMediaBusy(false);

                showToast(
                    ok
                        ? "Голосовое сообщение отправлено"
                        : "Не удалось отправить голосовое сообщение.",
                    ok ? "ok" : "error"
                );
            }
        );
}


function blobToAudioFile(blob) {

    const type =
        blob.type || "";

    let extension =
        ".weba";

    if (type.startsWith("audio/webm")) {
        extension = ".weba";

    } else if (type.startsWith("audio/mp4")) {
        extension = ".m4a";

    } else if (type.startsWith("audio/mpeg")) {
        extension = ".mp3";

    } else if (type.startsWith("audio/ogg")) {
        extension = ".ogg";

    } else if (type.startsWith("audio/opus")) {
        extension = ".opus";

    } else if (type.startsWith("audio/wav")) {
        extension = ".wav";
    }

    const name =
        `voice_message_${Date.now()}${extension}`;

    return new File(
        [blob],
        name,
        {
            type: type || "audio/webm",
        }
    );
}


function updateRecordingTime() {

    const elapsed =
        Date.now() - recordStartTime;

    if (elapsed >= MAX_RECORD_MS) {

        stopRecording();

        return;
    }

    const totalSeconds =
        Math.floor(
            elapsed / 1000
        );

    const minutes =
        String(
            Math.floor(
                totalSeconds / 60
            )
        ).padStart(2, "0");

    const seconds =
        String(
            totalSeconds % 60
        ).padStart(2, "0");

    if (chatRecordingTime) {

        chatRecordingTime.textContent =
            `${minutes}:${seconds}`;
    }
}


function setRecordingUi(active) {

    if (chatRecordingBar) {
        chatRecordingBar.hidden =
            !active;
    }

    if (chatRecordButton) {

        chatRecordButton.classList.toggle(
            "recording",
            active
        );
    }

    const chatInputElement =
        document.querySelector(
            ".chat-input"
        );

    if (chatInputElement) {

        chatInputElement.classList.toggle(
            "recording",
            active
        );
    }

    if (chatAttachButton) {
        chatAttachButton.disabled =
            active;
    }

    if (messageInput) {
        messageInput.hidden =
            active;
    }

    const replyPreview =
        document.getElementById(
            "chat-reply-preview"
        );

    if (replyPreview) {
        replyPreview.hidden =
            active;
    }

    if (messageSubmitButton) {
        messageSubmitButton.hidden =
            active
            ||
            !messageInput
            ||
            !messageInput.value.trim();
    }
}


if (chatRecordButton) {

    chatRecordButton.addEventListener(
        "pointerdown",
        beginRecordHold
    );

    chatRecordButton.addEventListener(
        "pointerup",
        releaseRecordButton
    );

    chatRecordButton.addEventListener(
        "pointercancel",
        function () {

            if (!isRecording) {
                cancelRecordHold();
            }
        }
    );

    chatRecordButton.addEventListener(
        "pointerleave",
        function () {

            if (!isRecording) {
                cancelRecordHold();
            }
        }
    );

    chatRecordButton.addEventListener(
        "contextmenu",
        function (event) {
            event.preventDefault();
        }
    );
}


// Отпустили кнопку где угодно — запись завершается.
document.addEventListener(
    "pointerup",
    function () {

        if (isRecording) {
            stopRecording();
        }
    }
);


updateInputMode();


// ==================================================
// Toast notifications
// ==================================================

let toastTimer = null;


function showToast(
    message,
    type
) {

    const toast =
        createToastElement();

    toast.textContent =
        message;

    toast.classList.toggle(
        "ok",
        type === "ok"
    );

    toast.classList.toggle(
        "error",
        type === "error"
    );

    toast.classList.add(
        "visible"
    );

    clearTimeout(toastTimer);

    toastTimer =
        setTimeout(
            function () {

                toast.classList.remove(
                    "visible"
                );
            },
            3000
        );
}


function createToastElement() {

    let toast =
        document.querySelector(
            ".chat-toast"
        );

    if (!toast) {

        toast =
            document.createElement(
                "div"
            );

        toast.classList.add(
            "chat-toast"
        );

        document.body.appendChild(
            toast
        );
    }

    return toast;
}


// ==================================================
// Send media (файлы, фото, видео, аудио)
// ==================================================

const chatAttachButton =
    document.getElementById(
        "chat-attach-button"
    );


const chatFileInput =
    document.getElementById(
        "chat-file-input"
    );


const chatUploadPanel =
    document.getElementById(
        "chat-upload-panel"
    );


const chatUploadFiles =
    document.getElementById(
        "chat-upload-files"
    );


const chatUploadCaption =
    document.getElementById(
        "chat-upload-caption"
    );


const chatUploadSend =
    document.getElementById(
        "chat-upload-send"
    );


const chatUploadCancel =
    document.getElementById(
        "chat-upload-cancel"
    );


const chatUploadStatus =
    document.getElementById(
        "chat-upload-status"
    );


let selectedFiles =
    [];


let mediaBusy =
    false;


function formatFileSize(
    bytes
) {

    if (bytes < 1024) {

        return bytes + " Б";
    }

    if (bytes < 1024 * 1024) {

        return (
            (bytes / 1024).toFixed(1) +
            " КБ"
        );
    }

    return (
        (bytes / (1024 * 1024)).toFixed(1) +
        " МБ"
    );
}


function showUploadPanel() {

    if (!chatUploadPanel) {
        return;
    }

    chatUploadPanel.classList.remove(
        "hidden"
    );

    chatUploadCaption?.focus();
}


function hideUploadPanel() {

    selectedFiles = [];

    chatUploadPanel?.classList.add(
        "hidden"
    );

    if (chatUploadFiles) {
        chatUploadFiles.textContent = "";
    }

    if (chatUploadStatus) {
        chatUploadStatus.textContent = "";
    }

    if (chatUploadCaption) {
        chatUploadCaption.value = "";
    }
}


function setMediaBusy(busy) {

    mediaBusy = busy;

    if (chatAttachButton) {
        chatAttachButton.disabled = busy;
    }

    if (messageSubmitButton) {
        messageSubmitButton.disabled = busy;
    }

    if (chatRecordButton) {
        chatRecordButton.disabled = busy;
    }

    if (chatUploadSend) {
        chatUploadSend.disabled = busy;
    }

    if (chatUploadCancel) {
        chatUploadCancel.disabled = busy;
    }
}


function renderUploadPanel() {

    if (!chatUploadFiles) {
        return;
    }

    chatUploadFiles.textContent =
        "";

    selectedFiles.forEach(
        function (item, index) {

            const row =
                document.createElement(
                    "div"
                );

            row.classList.add(
                "upload-file"
            );


            const name =
                document.createElement(
                    "span"
                );

            name.classList.add(
                "upload-file-name"
            );

            name.textContent =
                item.file.name;

            name.title =
                item.file.name;


            const size =
                document.createElement(
                    "span"
                );

            size.classList.add(
                "upload-file-size"
            );

            size.textContent =
                formatFileSize(
                    item.file.size
                );


            const status =
                document.createElement(
                    "span"
                );

            status.classList.add(
                "upload-file-status"
            );

            if (
                item.status === "uploading"
            ) {

                status.classList.add(
                    "spinner"
                );

            } else if (
                item.status === "ok"
            ) {

                status.classList.add(
                    "ok"
                );

                status.textContent =
                    "✓";

            } else if (
                item.status === "error"
            ) {

                status.classList.add(
                    "error"
                );

                status.textContent =
                    "!";
            }


            const remove =
                document.createElement(
                    "button"
                );

            remove.type =
                "button";

            remove.className =
                "upload-file-remove";

            remove.textContent =
                "×";

            remove.title =
                "Убрать файл";

            remove.disabled =
                mediaBusy;

            remove.addEventListener(
                "click",
                function () {

                    selectedFiles.splice(
                        index,
                        1
                    );

                    renderUploadPanel();

                    if (
                        selectedFiles.length === 0
                    ) {

                        hideUploadPanel();
                    }
                }
            );


            row.appendChild(name);
            row.appendChild(size);
            row.appendChild(status);
            row.appendChild(remove);

            chatUploadFiles.appendChild(
                row
            );
        }
    );
}


if (chatAttachButton) {

    chatAttachButton.addEventListener(
        "click",
        function () {

            chatFileInput?.click();
        }
    );
}


if (chatFileInput) {

    chatFileInput.addEventListener(
        "change",
        function () {

            const files =
                Array.from(
                    chatFileInput.files || []
                );

            chatFileInput.value =
                "";

            if (files.length === 0) {
                return;
            }

            files.forEach(
                function (file) {

                    selectedFiles.push({
                        file: file,
                        status: "pending",
                    });
                }
            );

            // Если в поле сообщения уже был текст —
            // используем его как комментарий к медиа.
            if (
                messageInput
                &&
                messageInput.value.trim()
            ) {

                chatUploadCaption.value =
                    messageInput.value.trim();

                messageInput.value = "";

                updateInputMode();
            }

            showUploadPanel();
            renderUploadPanel();
        }
    );
}


if (chatUploadSend) {

    chatUploadSend.addEventListener(
        "click",
        sendSelectedMedia
    );
}


if (chatUploadCaption) {

    chatUploadCaption.addEventListener(
        "keydown",
        function (event) {

            if (event.key === "Enter") {

                event.preventDefault();

                sendSelectedMedia();
            }
        }
    );
}


if (chatUploadCancel) {

    chatUploadCancel.addEventListener(
        "click",
        hideUploadPanel
    );
}


async function sendSelectedMedia() {

    if (selectedFiles.length === 0) {
        return;
    }

    if (
        !chatSocket
        ||
        chatSocket.readyState !== WebSocket.OPEN
    ) {

        showToast(
            "Соединение с чатом потеряно. " +
            "Перезагрузите страницу.",
            "error"
        );

        return;
    }

    const caption =
        chatUploadCaption
            ? chatUploadCaption.value.trim()
            : "";

    const total =
        selectedFiles.length;

    let done = 0;
    let failed = 0;

    setMediaBusy(true);

    for (
        const item of selectedFiles
    ) {

        if (item.status === "ok") {

            done += 1;
            continue;
        }

        item.status = "uploading";
        item.error = "";
        renderUploadPanel();

        if (chatUploadStatus) {

            chatUploadStatus.textContent =
                `Отправка ${done + 1} из ${total}...`;
        }

        const ok =
            await uploadMediaFile(
                item.file,
                caption,
                pendingReply
            );

        if (ok) {

            item.status = "ok";
            done += 1;

        } else {

            item.status = "error";
            failed += 1;
        }

        renderUploadPanel();
    }

    setMediaBusy(false);

    if (chatUploadStatus) {
        chatUploadStatus.textContent = "";
    }

    if (failed === 0) {

        showToast(
            total === 1
                ? "Файл отправлен"
                : `Отправлено файлов: ${total}`,
            "ok"
        );

        hideUploadPanel();

        cancelReplyPreview();

        messageInput?.focus();

    } else {

        showToast(
            "Не удалось отправить некоторые файлы.",
            "error"
        );
    }
}


async function uploadMediaFile(
    file,
    caption,
    replyToId
) {

    const formData =
        new FormData();

    formData.append("file", file);

    formData.append("caption", caption || "");

    if (replyToId) {

        formData.append(
            "reply_to_id",
            replyToId
        );
    }


    try {

        const response =
            await apiRequest(
                chatConfig.sendFileUrl,
                {
                    method: "POST",

                    body: formData,
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            const errorMessages =
                extractFormErrors(
                    data.errors
                );

            console.error(
                "Upload failed:",
                errorMessages || data.error
            );

            return false;
        }


        // Сообщение с файлом рассылается сервером
        // всем участникам комнаты, включая отправителя.

        return true;

    } catch (error) {

        console.error(
            "Upload error:",
            error
        );

        return false;
    }
}


// ==================================================
// Authentication
// ==================================================

if (loginForm) {

    loginForm.addEventListener(
        "submit",
        handleLogin
    );
}


async function handleLogin(event) {

    event.preventDefault();


    const username =
        document.getElementById(
            "login-username"
        ).value;


    const password =
        document.getElementById(
            "login-password"
        ).value;


    const errorElement =
        document.getElementById(
            "login-error"
        );


    errorElement.textContent =
        "Выполняется вход...";


    try {

        const response =
            await apiRequest(
                chatConfig.loginUrl,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/x-www-form-urlencoded",
                    },

                    body:
                        new URLSearchParams({
                            username,
                            password,
                        }),
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            errorElement.textContent =
                data.error ||
                "Ошибка входа.";

            return;
        }


        window.location.reload();

    } catch (error) {

        console.error(
            "Login error:",
            error
        );

        errorElement.textContent =
            "Ошибка сети. Попробуйте позже.";
    }
}


if (registerForm) {

    registerForm.addEventListener(
        "submit",
        handleRegistration
    );
}


async function handleRegistration(event) {

    event.preventDefault();


    const username =
        document.getElementById(
            "register-username"
        ).value;


    const email =
        document.getElementById(
            "register-email"
        ).value;


    const password =
        document.getElementById(
            "register-password"
        ).value;


    const passwordConfirm =
        document.getElementById(
            "register-password-confirm"
        ).value;


    const errorElement =
        document.getElementById(
            "register-error"
        );


    errorElement.textContent =
        "Создание аккаунта...";


    try {

        const response =
            await apiRequest(
                chatConfig.registerUrl,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/x-www-form-urlencoded",
                    },

                    body:
                        new URLSearchParams({
                            username,
                            email,
                            password,
                            password_confirm:
                                passwordConfirm,
                        }),
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            showRegistrationErrors(
                data.errors
                ||
                {
                    general: [
                        "Ошибка регистрации",
                    ],
                }
            );

            return;
        }


        window.location.reload();

    } catch (error) {

        console.error(
            "Registration error:",
            error
        );

        errorElement.textContent =
            "Ошибка сети. Попробуйте позже.";
    }
}


function showRegistrationErrors(errors) {

    const errorElement =
        document.getElementById(
            "register-error"
        );


    if (!errorElement) {
        return;
    }


    errorElement.textContent =
        extractFormErrors(errors);
}


// ==================================================
// Authentication modal switching
// ==================================================

if (showRegisterButton) {

    showRegisterButton.addEventListener(
        "click",
        function () {

            loginContainer?.classList.add(
                "hidden"
            );

            registerContainer?.classList.remove(
                "hidden"
            );


            const error =
                document.getElementById(
                    "register-error"
                );

            if (error) {
                error.textContent = "";
            }
        }
    );
}


if (showLoginButton) {

    showLoginButton.addEventListener(
        "click",
        function () {

            registerContainer?.classList.add(
                "hidden"
            );

            loginContainer?.classList.remove(
                "hidden"
            );


            const error =
                document.getElementById(
                    "login-error"
                );

            if (error) {
                error.textContent = "";
            }
        }
    );
}


// ==================================================
// User menu
// ==================================================

const userMenuButton =
    document.getElementById(
        "user-menu-button"
    );


const userMenuDropdown =
    document.getElementById(
        "user-menu-dropdown"
    );


const logoutButton =
    document.getElementById(
        "logout-button"
    );


if (userMenuButton) {

    userMenuButton.addEventListener(
        "click",
        function (event) {

            event.stopPropagation();

            userMenuDropdown?.classList.toggle(
                "hidden"
            );
        }
    );
}


if (logoutButton) {

    logoutButton.addEventListener(
        "click",
        handleLogout
    );
}


async function handleLogout() {

    shouldReconnect = false;

    clearTimeout(
        reconnectTimeout
    );


    if (chatSocket) {

        chatSocket.onclose = null;

        chatSocket.close();
    }


    try {

        const response =
            await apiRequest(
                chatConfig.logoutUrl,
                {
                    method: "POST",
                }
            );


        if (response.ok) {

            window.location.reload();

        } else {

            console.error(
                "Logout failed:",
                response.status
            );
        }

    } catch (error) {

        console.error(
            "Logout error:",
            error
        );
    }
}


// ==================================================
// Room menu
// ==================================================

const roomMenuButton =
    document.getElementById(
        "room-menu-button"
    );


const roomMenuDropdown =
    document.getElementById(
        "room-menu-dropdown"
    );


if (roomMenuButton) {

    roomMenuButton.addEventListener(
        "click",
        function (event) {

            event.stopPropagation();


            userMenuDropdown?.classList.add(
                "hidden"
            );


            roomMenuDropdown?.classList.toggle(
                "hidden"
            );
        }
    );
}


// ==================================================
// Global menu closing
// ==================================================

document.addEventListener(
    "click",
    function () {

        userMenuDropdown?.classList.add(
            "hidden"
        );

        roomMenuDropdown?.classList.add(
            "hidden"
        );
    }
);


// ==================================================
// Create room
// ==================================================

const createRoomButton =
    document.getElementById(
        "create-room-button"
    );


const createRoomModal =
    document.getElementById(
        "create-room-modal"
    );


const createRoomForm =
    document.getElementById(
        "create-room-form"
    );


const createRoomError =
    document.getElementById(
        "create-room-error"
    );


if (createRoomButton) {

    createRoomButton.addEventListener(
        "click",
        function () {

            createRoomForm?.reset();

            clearModalError(
                createRoomError
            );

            openModal(
                createRoomModal
            );
        }
    );
}


if (createRoomForm) {

    createRoomForm.addEventListener(
        "submit",
        handleCreateRoom
    );
}


async function handleCreateRoom(event) {

    event.preventDefault();


    clearModalError(
        createRoomError
    );


    const submitButton =
        createRoomForm.querySelector(
            "button[type=submit]"
        );


    submitButton.disabled = true;

    submitButton.textContent =
        "Создание...";


    try {

        const response =
            await apiRequest(
                chatConfig.createRoomUrl,
                {
                    method: "POST",

                    body:
                        new FormData(
                            createRoomForm
                        ),
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            showModalError(
                createRoomError,
                extractFormErrors(
                    data.errors
                )
                ||
                data.error
                ||
                "Не удалось создать комнату."
            );

            return;
        }


        closeModal(
            createRoomModal
        );


        const roomUrl =
            chatConfig.roomUrlTemplate
                .replace(
                    "ROOM_NAME",
                    encodeURIComponent(
                        data.room.name
                    )
                );


        window.location.href =
            roomUrl;

    } catch (error) {

        console.error(
            "Create room error:",
            error
        );

        showModalError(
            createRoomError,
            "Ошибка сети. Попробуйте позже."
        );

    } finally {

        submitButton.disabled = false;

        submitButton.textContent =
            "Создать";
    }
}


// ==================================================
// Edit room
// ==================================================

const editRoomButton =
    document.getElementById(
        "edit-room-button"
    );


const editRoomModal =
    document.getElementById(
        "edit-room-modal"
    );


const editRoomForm =
    document.getElementById(
        "edit-room-form"
    );


const editRoomError =
    document.getElementById(
        "edit-room-error"
    );


if (editRoomButton) {

    editRoomButton.addEventListener(
        "click",
        function () {

            roomMenuDropdown?.classList.add(
                "hidden"
            );

            clearModalError(
                editRoomError
            );

            openModal(
                editRoomModal
            );
        }
    );
}


if (editRoomForm) {

    editRoomForm.addEventListener(
        "submit",
        handleEditRoom
    );
}


async function handleEditRoom(event) {

    event.preventDefault();


    clearModalError(
        editRoomError
    );


    const submitButton =
        editRoomForm.querySelector(
            "button[type=submit]"
        );


    submitButton.disabled = true;

    submitButton.textContent =
        "Сохранение...";


    try {

        const response =
            await apiRequest(
                chatConfig.updateRoomUrl,
                {
                    method: "POST",

                    body:
                        new FormData(
                            editRoomForm
                        ),
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            showModalError(
                editRoomError,
                extractFormErrors(
                    data.errors
                )
                ||
                data.error
                ||
                "Не удалось изменить комнату."
            );

            return;
        }


        updateRoomInterface(
            data.room
        );


        closeModal(
            editRoomModal
        );


        const roomUrl =
            chatConfig.roomUrlTemplate
                .replace(
                    "ROOM_NAME",
                    encodeURIComponent(
                        data.room.name
                    )
                );


        window.location.href =
            roomUrl;

    } catch (error) {

        console.error(
            "Update room error:",
            error
        );

        showModalError(
            editRoomError,
            "Ошибка сети. Попробуйте позже."
        );

    } finally {

        submitButton.disabled = false;

        submitButton.textContent =
            "Сохранить";
    }
}


function updateRoomInterface(room) {

    const title =
        document.getElementById(
            "room-title-name"
        );


    const menuName =
        document.getElementById(
            "room-menu-name"
        );


    const description =
        document.getElementById(
            "room-menu-description"
        );


    if (title) {
        title.textContent =
            room.name;
    }


    if (menuName) {
        menuName.textContent =
            room.name;
    }


    if (description) {

        description.textContent =
            room.description
            ||
            "Без описания";
    }


    updateRoomAvatar(
        "room-avatar",
        room
    );


    updateRoomAvatar(
        "room-menu-avatar",
        room
    );
}


function updateRoomAvatar(
    elementId,
    room
) {

    const element =
        document.getElementById(
            elementId
        );


    if (!element) {
        return;
    }


    element.innerHTML = "";


    if (room.avatar) {

        const image =
            document.createElement("img");

        image.src =
            room.avatar;

        image.alt =
            room.name;

        element.appendChild(image);

    } else {

        element.textContent =
            room.name
                .charAt(0)
                .toUpperCase();
    }
}


// ==================================================
// Add member
// ==================================================

const addMemberButton =
    document.getElementById(
        "add-member-button"
    );


const addMemberModal =
    document.getElementById(
        "add-member-modal"
    );


const addMemberForm =
    document.getElementById(
        "add-member-form"
    );


const addMemberError =
    document.getElementById(
        "add-member-error"
    );


if (addMemberButton) {

    addMemberButton.addEventListener(
        "click",
        function () {

            clearModalError(
                addMemberError
            );

            openModal(
                addMemberModal
            );
        }
    );
}


if (addMemberForm) {

    addMemberForm.addEventListener(
        "submit",
        handleAddMember
    );
}


async function handleAddMember(event) {

    event.preventDefault();


    clearModalError(
        addMemberError
    );


    const submitButton =
        addMemberForm.querySelector(
            "button[type=submit]"
        );


    submitButton.disabled = true;

    submitButton.textContent =
        "Добавление...";


    try {

        const response =
            await apiRequest(
                chatConfig.addMemberUrl,
                {
                    method: "POST",

                    body:
                        new FormData(
                            addMemberForm
                        ),
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            showModalError(
                addMemberError,
                extractFormErrors(
                    data.errors
                )
                ||
                data.error
                ||
                "Не удалось добавить участника."
            );

            return;
        }


        addMemberToMenu(
            data.member
        );


        removeUserFromAvailableList(
            data.member.id
        );


        addMemberForm.reset();


        closeModal(
            addMemberModal
        );

    } catch (error) {

        console.error(
            "Add member error:",
            error
        );

        showModalError(
            addMemberError,
            "Ошибка сети. Попробуйте позже."
        );

    } finally {

        submitButton.disabled = false;

        submitButton.textContent =
            "Добавить";
    }
}


function addMemberToMenu(member) {

    const list =
        document.getElementById(
            "room-members-list"
        );


    if (!list) {
        return;
    }


    const element =
        document.createElement("div");

    element.classList.add(
        "room-member"
    );


    element.dataset.userId =
        member.id;

    element.dataset.username =
        member.username;


    const avatar =
        document.createElement("div");

    avatar.classList.add(
        "room-member-avatar"
    );


    if (member.avatar) {

        const image =
            document.createElement("img");

        image.src =
            member.avatar;

        image.alt =
            member.username;

        avatar.appendChild(image);

    } else {

        avatar.textContent =
            member.username
                .charAt(0)
                .toUpperCase();
    }


    const status =
        document.createElement("span");

    status.classList.add(
        "participant-status"
    );


    const username =
        document.createElement("span");

    username.classList.add(
        "room-member-name"
    );

    username.textContent =
        member.username;


    element.appendChild(avatar);
    element.appendChild(status);
    element.appendChild(username);


    if (chatConfig.isRoomOwner && !chatConfig.isDirect) {

        const removeButton =
            document.createElement("button");

        removeButton.type = "button";

        removeButton.classList.add(
            "remove-member-button"
        );

        removeButton.dataset.userId =
            member.id;

        removeButton.title =
            "Удалить участника";

        removeButton.textContent =
            "×";


        removeButton.addEventListener(
            "click",
            function () {

                removeRoomMember(
                    member.id,
                    member.username,
                    element
                );
            }
        );


        element.appendChild(
            removeButton
        );
    }


    list.appendChild(
        element
    );


    updateRoomMembersCount();
}


function removeUserFromAvailableList(
    userId
) {

    const select =
        document.getElementById(
            "add-member-user"
        );


    if (!select) {
        return;
    }


    const option =
        select.querySelector(
            `option[value="${userId}"]`
        );


    option?.remove();
}


// ==================================================
// Room media (панель «Медиа»)
// ==================================================

const mediaButton =
    document.getElementById(
        "media-button"
    );

const mediaModal =
    document.getElementById(
        "media-modal"
    );

const mediaTabs =
    document.getElementById(
        "media-tabs"
    );

const mediaGallery =
    document.getElementById(
        "media-gallery"
    );

let roomMediaData = null;

let activeMediaTab = "photos";


if (
    mediaButton
    &&
    mediaModal
) {

    mediaButton.addEventListener(
        "click",
        function () {

            roomMenuDropdown?.classList.add(
                "hidden"
            );

            openModal(
                mediaModal
            );

            loadRoomMedia();
        }
    );
}


if (mediaTabs) {

    mediaTabs.addEventListener(
        "click",
        function (event) {

            const tabButton =
                event.target.closest(
                    "[data-media-tab]"
                );

            if (!tabButton) {
                return;
            }

            activeMediaTab =
                tabButton.dataset.mediaTab;

            mediaTabs
                .querySelectorAll(
                    "[data-media-tab]"
                )
                .forEach(
                    function (button) {

                        button.classList.toggle(
                            "active",
                            button === tabButton
                        );
                    }
                );

            renderMediaTab(
                activeMediaTab
            );
        }
    );
}


async function loadRoomMedia() {

    if (!mediaGallery) {
        return;
    }

    mediaGallery.textContent =
        "Загрузка...";

    mediaGallery.classList.add(
        "media-loading"
    );

    try {

        const response =
            await apiRequest(
                chatConfig.mediaUrl,
                {
                    method: "GET",
                }
            );

        if (!response.ok) {

            renderMediaError(
                "Не удалось загрузить медиа."
            );

            return;
        }

        roomMediaData =
            await response.json();

        updateMediaCounts();

        renderMediaTab(
            activeMediaTab
        );

    } catch (error) {

        console.error(
            "Media load error:",
            error
        );

        renderMediaError(
            "Ошибка сети. Попробуйте позже."
        );
    }
}


function renderMediaError(message) {

    if (!mediaGallery) {
        return;
    }

    mediaGallery.textContent = "";

    const empty =
        document.createElement("div");

    empty.className =
        "media-empty";

    empty.textContent =
        message;

    mediaGallery.appendChild(
        empty
    );
}


function updateMediaCounts() {

    if (
        !roomMediaData
        ||
        !mediaTabs
    ) {
        return;
    }

    mediaTabs
        .querySelectorAll(
            "[data-media-tab]"
        )
        .forEach(
            function (button) {

                const tab =
                    button.dataset.mediaTab;

                const count =
                    (roomMediaData[tab] || [])
                        .length;

                const countElement =
                    button.querySelector(
                        ".media-tab-count"
                    );

                if (countElement) {

                    countElement.textContent =
                        String(count);
                }
            }
        );
}


function renderMediaTab(tab) {

    if (!mediaGallery) {
        return;
    }

    mediaGallery.textContent = "";

    mediaGallery.classList.remove(
        "media-loading"
    );

    const items =
        roomMediaData?.[tab] || [];

    if (items.length === 0) {

        const empty =
            document.createElement("div");

        empty.className =
            "media-empty";

        empty.textContent =
            "Пока нет материалов в этой категории.";

        mediaGallery.appendChild(
            empty
        );

        return;
    }

    if (
        tab === "photos"
        ||
        tab === "videos"
    ) {

        const grid =
            document.createElement("div");

        grid.className =
            "media-grid";

        items.forEach(
            function (item) {

                grid.appendChild(
                    createMediaTile(
                        item,
                        tab
                    )
                );
            }
        );

        mediaGallery.appendChild(
            grid
        );

    } else {

        const list =
            document.createElement("div");

        list.className =
            "media-list";

        items.forEach(
            function (item) {

                list.appendChild(
                    createMediaRow(
                        item,
                        tab
                    )
                );
            }
        );

        mediaGallery.appendChild(
            list
        );
    }
}


function createMediaTile(item, kind) {

    const link =
        document.createElement("a");

    link.className =
        "media-grid-item";

    link.href =
        item.attachment;

    link.target = "_blank";

    link.rel = "noopener";

    link.title =
        item.attachment_name
        ||
        item.username;


    if (kind === "videos") {

        const video =
            document.createElement("video");

        video.src =
            item.attachment;

        video.muted = true;

        video.preload = "metadata";

        video.setAttribute(
            "playsinline",
            ""
        );

        link.appendChild(
            video
        );

        const play =
            document.createElement("span");

        play.className =
            "media-tile-play";

        play.textContent = "▶";

        link.appendChild(
            play
        );

    } else {

        const image =
            document.createElement("img");

        image.src =
            item.attachment;

        image.alt =
            item.attachment_name
            ||
            "Фото";

        image.loading = "lazy";

        link.appendChild(
            image
        );
    }


    const overlay =
        document.createElement("span");

    overlay.className =
        "media-tile-overlay";

    const meta =
        document.createElement("span");

    meta.className =
        "media-tile-meta";

    meta.textContent =
        item.username;

    overlay.appendChild(
        meta
    );

    if (item.text) {

        const caption =
            document.createElement("span");

        caption.className =
            "media-tile-caption";

        caption.textContent =
            item.text;

        overlay.appendChild(
            caption
        );
    }

    link.appendChild(
        overlay
    );

    return link;
}


function createMediaRow(item, kind) {

    const link =
        document.createElement("a");

    link.className =
        "media-list-item";

    link.target = "_blank";

    link.rel = "noopener";

    link.href =
        kind === "links"
            ? item.link
            : item.attachment;


    const icon =
        document.createElement("span");

    icon.className =
        "media-list-icon";

    icon.textContent =
        kind === "links"
            ? "🔗"
            : "📄";

    link.appendChild(
        icon
    );


    const body =
        document.createElement("span");

    body.className =
        "media-list-body";

    const name =
        document.createElement("span");

    name.className =
        "media-list-name";

    name.textContent =
        kind === "links"
            ? (item.link || "")
            : (item.attachment_name || "Файл");

    body.appendChild(
        name
    );


    const meta =
        document.createElement("span");

    meta.className =
        "media-list-meta";

    meta.textContent =
        [
            item.username,
            formatMediaDate(
                item.created_at
            ),
        ]
        .filter(Boolean)
        .join(" • ");

    body.appendChild(
        meta
    );


    link.appendChild(
        body
    );

    return link;
}


function formatMediaDate(iso) {

    const date =
        new Date(iso);

    if (isNaN(date)) {
        return "";
    }

    return date.toLocaleString(
        "ru-RU",
        {
            day: "2-digit",
            month: "2-digit",
            year: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        }
    );
}


// ==================================================
// Remove member
// ==================================================

document
    .querySelectorAll(
        ".remove-member-button"
    )
    .forEach(
        function (button) {

            button.addEventListener(
                "click",
                function (event) {

                    event.stopPropagation();


                    const userId =
                        button.dataset.userId;


                    const member =
                        button.closest(
                            ".room-member"
                        );


                    if (!member) {
                        return;
                    }


                    const username =
                        member.dataset.username;


                    removeRoomMember(
                        userId,
                        username,
                        member
                    );
                }
            );
        }
    );


async function removeRoomMember(
    userId,
    username,
    element
) {

    const confirmed =
        confirm(
            `Удалить ${username} из комнаты?`
        );


    if (!confirmed) {
        return;
    }


    try {

        const response =
            await apiRequest(
                chatConfig.removeMemberUrlTemplate
                    .replace(
                        "/0/remove/",
                        "/" + userId + "/remove/"
                    ),
                {
                    method: "POST",
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            alert(
                data.error ||
                "Не удалось удалить участника."
            );

            return;
        }


        element.remove();

        updateRoomMembersCount();

    } catch (error) {

        console.error(
            "Remove member error:",
            error
        );

        alert(
            "Ошибка сети. Попробуйте позже."
        );
    }
}


// ==================================================
// Join room
// ==================================================

const joinRoomButton =
    document.getElementById(
        "join-room-button"
    );


if (joinRoomButton) {

    joinRoomButton.addEventListener(
        "click",
        handleJoinRoom
    );
}


async function handleJoinRoom() {

    joinRoomButton.disabled = true;

    joinRoomButton.textContent =
        "Вступление...";


    try {

        const response =
            await apiRequest(
                chatConfig.joinRoomUrl,
                {
                    method: "POST",
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            alert(
                data.error ||
                "Не удалось вступить в комнату."
            );

            return;
        }


        window.location.reload();

    } catch (error) {

        console.error(
            "Join room error:",
            error
        );

        alert(
            "Ошибка сети. Попробуйте позже."
        );

    } finally {

        joinRoomButton.disabled = false;

        joinRoomButton.textContent =
            "Вступить в комнату";
    }
}


// ==================================================
// Leave room
// ==================================================

const leaveRoomButton =
    document.getElementById(
        "leave-room-button"
    );


if (leaveRoomButton) {

    leaveRoomButton.addEventListener(
        "click",
        handleLeaveRoom
    );
}


async function handleLeaveRoom() {

    const confirmed =
        confirm(
            "Вы действительно хотите покинуть этот чат?"
        );


    if (!confirmed) {
        return;
    }


    leaveRoomButton.disabled = true;

    leaveRoomButton.textContent =
        "Выход...";


    try {

        const response =
            await apiRequest(
                chatConfig.leaveRoomUrl,
                {
                    method: "POST",
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            alert(
                data.error ||
                "Не удалось покинуть чат."
            );

            return;
        }


        shouldReconnect = false;

        clearTimeout(
            reconnectTimeout
        );


        if (chatSocket) {

            chatSocket.onclose = null;

            chatSocket.close();
        }


        window.location.href =
            data.redirect_url;

    } catch (error) {

        console.error(
            "Leave room error:",
            error
        );

        alert(
            "Ошибка сети. Попробуйте позже."
        );

    } finally {

        leaveRoomButton.disabled = false;

        leaveRoomButton.textContent =
            "🚪 Покинуть чат";
    }
}


// ==================================================
// Room members count
// ==================================================

function updateRoomMembersCount() {

    const list =
        document.getElementById(
            "room-members-list"
        );


    if (!list) {
        return;
    }


    const count =
        list.querySelectorAll(
            ".room-member"
        ).length;


    const headerCount =
        document.getElementById(
            "room-members-count"
        );


    const menuCount =
        document.getElementById(
            "room-members-menu-count"
        );


    if (headerCount) {

        headerCount.textContent =
            count;
    }


    if (menuCount) {

        menuCount.textContent =
            count;
    }
}


// ==================================================
// Modals
// ==================================================

document
    .querySelectorAll(
        "[data-close-modal]"
    )
    .forEach(
        function (button) {

            button.addEventListener(
                "click",
                function () {

                    const modalId =
                        button.dataset.closeModal;


                    closeModal(
                        document.getElementById(
                            modalId
                        )
                    );
                }
            );
        }
    );


document
    .querySelectorAll(".modal")
    .forEach(
        function (modal) {

            modal.addEventListener(
                "click",
                function (event) {

                    if (
                        event.target === modal
                    ) {

                        closeModal(
                            modal
                        );
                    }
                }
            );
        }
    );


document.addEventListener(
    "keydown",
    function (event) {

        if (event.key !== "Escape") {
            return;
        }


        document
            .querySelectorAll(".modal")
            .forEach(
                function (modal) {

                    if (
                        !modal.classList.contains(
                            "hidden"
                        )
                    ) {

                        closeModal(
                            modal
                        );
                    }
                }
            );
    }
);


// ==================================================
// Rooms sidebar
// ==================================================

const roomsSidebar =
    document.getElementById(
        "rooms-sidebar"
    );


const roomsToggleButton =
    document.getElementById(
        "rooms-toggle-button"
    );


function setRoomsSidebarState(
    collapsed
) {

    if (!roomsSidebar) {
        return;
    }


    roomsSidebar.classList.toggle(
        "collapsed",
        collapsed
    );


    if (roomsToggleButton) {

        const label =
            collapsed
                ? "Развернуть список комнат"
                : "Свернуть список комнат";


        roomsToggleButton.setAttribute(
            "aria-label",
            label
        );


        roomsToggleButton.setAttribute(
            "title",
            label
        );
    }


    localStorage.setItem(
        "chatRoomsSidebarCollapsed",
        collapsed
            ? "true"
            : "false"
    );
}


if (
    roomsSidebar
    &&
    roomsToggleButton
) {

    const savedState =
        localStorage.getItem(
            "chatRoomsSidebarCollapsed"
        );


    if (savedState === "true") {

        setRoomsSidebarState(
            true
        );
    }


    roomsToggleButton.addEventListener(
        "click",
        function (event) {

            event.stopPropagation();


            const collapsed =
                roomsSidebar.classList.contains(
                    "collapsed"
                );


            setRoomsSidebarState(
                !collapsed
            );
        }
    );
}


// ==================================================
// Поиск по чатам в сайдбаре
// ==================================================

const roomsSearchInput =
    document.getElementById(
        "rooms-search-input"
    );


const roomsFilteredEmpty =
    document.getElementById(
        "rooms-filtered-empty"
    );


const roomLinks =
    Array.from(
        document.querySelectorAll(
            ".rooms-list .room-link"
        )
    );


const roomsSections =
    Array.from(
        document.querySelectorAll(
            ".rooms-list .rooms-section"
        )
    );


function filterRooms() {

    if (!roomsSearchInput) {
        return;
    }

    const query =
        roomsSearchInput.value
            .trim()
            .toLowerCase();

    let visibleCount = 0;

    roomLinks.forEach(
        function (link) {

            const name =
                (
                    link.dataset.roomName
                    || link.textContent
                ).trim()
                .toLowerCase();

            const match =
                name.includes(query);

            link.hidden = !match;

            if (match) {
                visibleCount += 1;
            }
        }
    );

    roomsSections.forEach(
        function (section) {

            const title =
                section.querySelector(
                    ".rooms-section-title"
                );

            if (!title) {
                return;
            }

            let sectionVisible =
                false;

            const sectionLinks =
                section.querySelectorAll(
                    ".room-link"
                );

            sectionLinks.forEach(
                function (link) {

                    if (!link.hidden) {
                        sectionVisible = true;
                    }
                }
            );

            title.hidden =
                query !== ""
                &&
                !sectionVisible;
        }
    );

    if (roomsFilteredEmpty) {
        roomsFilteredEmpty.hidden =
            !(
                query
                &&
                visibleCount === 0
            );
    }
}


if (roomsSearchInput) {

    roomsSearchInput.addEventListener(
        "input",
        filterRooms
    );

    roomsSearchInput.addEventListener(
        "search",
        filterRooms
    );
}


// Обновляет бейдж непрочитанных в списке чатов в реальном времени.
function applyUnreadUpdate(data) {

    if (
        !data
        ||
        data.room_id === chatConfig.roomId
    ) {
        return;
    }

    const link =
        document.querySelector(
            `.room-link[data-room-id="${data.room_id}"]`
        );

    if (!link) {
        return;
    }

    const avatar =
        link.querySelector(
            ".room-avatar"
        );

    if (!avatar) {
        return;
    }

    let badge =
        avatar.querySelector(
            ".room-unread"
        );

    if (data.unread_count > 0) {

        if (!badge) {

            badge =
                document.createElement(
                    "span"
                );

            badge.className =
                "room-unread";

            badge.title =
                "Непрочитанные сообщения";

            avatar.appendChild(
                badge
            );
        }

        badge.textContent =
            data.unread_count;

        // Комнаты с непрочитанными в разделе «Чаты» поднимаются
        // наверх, как при перезагрузке (сортируются по убыванию).
        const section =
            link.closest(
                ".rooms-section"
            );

        if (
            section
            &&
            section.dataset.sectionName
                === "chats"
        ) {

            const firstRoomLink =
                section.querySelector(
                    ".room-link"
                );

            if (
                firstRoomLink
                &&
                firstRoomLink !== link
            ) {

                section.insertBefore(
                    link,
                    firstRoomLink
                );
            }
        }

    } else if (badge) {

        badge.remove();
    }
}


// Помечаем комнату прочитанной при поступлении нового сообщения
// (сообщения видны прямо сейчас, непрочитанными они не станут).
function markCurrentRoomRead() {

    if (
        !isAuthenticated
        ||
        !chatConfig.readUrl
    ) {
        return;
    }

    apiRequest(
        chatConfig.readUrl,
        {
            method: "POST",
        }
    ).catch(
        function () {
            // Ошибку пометки чтения игнорируем —
            // счётчик поправится при следующем открытии чата.
        }
    );
}
