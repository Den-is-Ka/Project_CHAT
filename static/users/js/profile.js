(function () {
    "use strict";

    const fileInput =
        document.getElementById("id_avatar");

    const fileName =
        document.getElementById("avatar-file-name");

    if (!fileInput || !fileName) {
        return;
    }

    fileInput.addEventListener(
        "change",
        function () {
            const file = fileInput.files[0];

            if (!file) {
                fileName.textContent = "";
                return;
            }

            fileName.textContent =
                "Выбран файл: " + file.name;
        }
    );
})();