FROM python:3.12-slim

# MUDIRAC is a dynamically linked Linux binary (needs libstdc++, libm, libgcc - all in this image)
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . /app
RUN chmod +x /app/mudirac && mkdir -p /app/simulation_outputs && chown -R user /app
USER user

EXPOSE 7860
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true", "--server.enableCORS=false", "--server.enableXsrfProtection=false", "--browser.gatherUsageStats=false"]
