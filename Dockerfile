# ==========================================
# Stage 1: Build the Application
# ==========================================
FROM maven:3.9.6-eclipse-temurin-21 AS builder
WORKDIR /build

# Copy the root pom.xml
COPY pom.xml .

# Copy all source code for proper reactor build
COPY smojol-cli smojol-cli
COPY smojol-api smojol-api
COPY smojol-toolkit smojol-toolkit
COPY smojol-core smojol-core
COPY mojo-common mojo-common
COPY woof woof
COPY che-che4z-lsp-for-cobol-integration che-che4z-lsp-for-cobol-integration

# Build all modules, skipping tests to save time/avoid environment issues
RUN mvn clean package -DskipTests

# ==========================================
# Stage 2: Runtime Environment
# ==========================================
FROM eclipse-temurin:21-jre-jammy

# 1. Install Runtime Dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv gnupg wget unzip \
    graphviz \
    libgraphviz-dev \
    pkg-config && \
    wget -q -O liquibase.tar.gz https://github.com/liquibase/liquibase/releases/download/v4.24.0/liquibase-4.24.0.tar.gz && \
    mkdir /opt/liquibase && \
    tar -xzf liquibase.tar.gz -C /opt/liquibase && \
    ln -s /opt/liquibase/liquibase /usr/local/bin/liquibase && \
    rm liquibase.tar.gz && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. Copy the API JAR (The Web Server) from builder
COPY --from=builder /build/smojol-api/target/smojol-api-*.jar /app/app.jar

# 3. FIX: Copy the CLI JAR (The Analysis Tool) from builder
COPY --from=builder /build/smojol-cli/target/smojol-cli-*.jar /app/cli.jar

# 4. Copy other necessary files
COPY db /app/db
COPY scripts /app/scripts
COPY smojol_python /app/smojol_python

# 5. Install Python Environment
RUN python3 -m venv /app/venv && \
    /app/venv/bin/pip install --upgrade pip && \
    /app/venv/bin/pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    /app/venv/bin/pip install --no-cache-dir -r /app/smojol_python/requirements.txt

# 6. Final Setup
RUN chmod +x /app/scripts/*.sh
EXPOSE 7070

# 7. Startup Script
RUN echo '#!/bin/bash\n\
    echo "[DEBUG] Launching Application..."\n\
    /app/scripts/up-db.sh\n\
    java -jar /app/app.jar' > /app/entrypoint.sh && chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]