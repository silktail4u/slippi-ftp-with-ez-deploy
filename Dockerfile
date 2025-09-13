# Use Python slim base
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies and system packages
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    libffi-dev \
    libssl-dev \
    iproute2 \
    gettext-base\
    sed\
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ARG USEHTTPS
ARG NAME
ARG FSURL

ENV USEHTTPS=${USEHTTPS}
ENV NAME=${NAME}
ENV FSURL=${FSURL}

# Copy the application code
COPY . .

RUN ls -la
RUN sed -i 's|sharlots|${NAME}|g' ./templates/index.html;
RUN sed -i 's|https://sharlot.memes.nz/slp-files|${FSURL}|g' ./templates/index.html;
RUN mv ./templates/index.html ./templates/index.template
RUN envsubst '${NAME} ${FSURL}' <./templates/index.template> ./templates/index.html;
RUN if [ "$USEHTTPS" = "FALSE" ]; then sed -i 's|https://|http://|g' ./templates/index.html; fi
RUN cat ./templates/index.html

# Create FTP root directory
RUN mkdir -p /web/sharlot/public_html/slp-files

# Expose ports
EXPOSE 21 9876
# Start the FTP + Flask server as root
CMD ["python", "sharlots-slippi-ftp-server.py"]

