ARG OPENWEBUI_IMAGE=ghcr.io/open-webui/open-webui:v0.12.5
FROM ${OPENWEBUI_IMAGE}

COPY tripz_image_studio.py install_local.py bootstrap.py setup_chat.py verify_edits.py start-tripz.sh /opt/tripz/
ENV ENABLE_OLLAMA_API=false \
    ENABLE_OPENAI_API=false \
    ENABLE_SIGNUP=false \
    DEFAULT_USER_ROLE=pending \
    ENABLE_VALVE_ENCRYPTION=true \
    TRIPZ_AUTO_INSTALL=true
CMD ["bash", "/opt/tripz/start-tripz.sh"]
