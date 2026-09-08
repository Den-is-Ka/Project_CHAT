from PIL import Image, ImageOps

AVATAR_SIZE = (300, 300)

# Защита от decompression bomb: отклоняем изображения больше ~20 Мпикс.,
# чтобы огромные картинки не «съедали» память при декодировании.
Image.MAX_IMAGE_PIXELS = 20_000_000


def resize_avatar(image):
    """Подгоняет изображение под размер аватара."""

    image = Image.open(image)

    image = ImageOps.exif_transpose(image)

    if image.mode != "RGB":
        image = image.convert("RGB")

    return ImageOps.fit(
        image,
        AVATAR_SIZE,
        method=Image.Resampling.LANCZOS,
    )
