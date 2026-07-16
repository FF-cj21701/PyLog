import base64

import pytest

from plugins.ai_assistant.ai_core.api_client import AsyncAIWorker
from plugins.ai_assistant.ui.main_window import normalize_chat_images


def image_payload(data=b"fake-png", name="sample.png", mime="image/png"):
    encoded = base64.b64encode(data).decode("ascii")
    return {
        "name": name,
        "mime_type": mime,
        "data_url": f"data:{mime};base64,{encoded}",
    }


def test_chat_image_payload_is_validated_and_normalized():
    images = normalize_chat_images([image_payload(name="../sample.png")])

    assert images == [{
        "name": "sample.png",
        "mime_type": "image/png",
        "size": len(b"fake-png"),
        "data_url": image_payload()["data_url"],
        "detail": "auto",
    }]


def test_chat_image_payload_rejects_unsupported_and_oversized_data():
    with pytest.raises(ValueError, match="supported PNG"):
        normalize_chat_images([image_payload(mime="image/svg+xml")])
    with pytest.raises(ValueError, match="between 1 byte"):
        normalize_chat_images([image_payload(data=b"12345")], max_image_bytes=4)
    with pytest.raises(ValueError, match="at most 4"):
        normalize_chat_images([image_payload()] * 5)


def test_worker_builds_standard_multimodal_user_content():
    image = normalize_chat_images([image_payload()])[0]
    worker = AsyncAIWorker(
        "key",
        "https://example.test/v1",
        "vision-model",
        "Describe the image",
        history=[("assistant", "Ready")],
        images=[image],
    )

    messages = worker._build_messages()
    content = messages[-1]["content"]

    assert content[0] == {"type": "text", "text": "Describe the image"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"] == {"url": image["data_url"], "detail": "auto"}


def test_chat_assets_include_attachment_preview_and_multimodal_payload():
    template = open("plugins/ai_assistant/ui/resources/chat_template.html", encoding="utf-8").read()
    bootstrap = open("plugins/ai_assistant/ui/resources/chat_bootstrap.js", encoding="utf-8").read()
    input_script = open("plugins/ai_assistant/ui/resources/chat_input.js", encoding="utf-8").read()
    message_script = open("plugins/ai_assistant/ui/resources/chat_message.js", encoding="utf-8").read()
    styles = open("plugins/ai_assistant/ui/resources/chat_styles.css", encoding="utf-8").read()

    assert 'id="image-preview-container"' in template
    assert 'id="attach-image-btn"' in template
    assert 'accept="image/png,image/jpeg,image/webp,image/gif"' in template
    assert "images: selectedImages" in input_script
    assert "clipboard.items" in bootstrap
    assert "await addImageFiles(imageFiles)" in bootstrap
    assert "renderUserMessageImages" in message_script
    assert ".image-preview-item" in styles
