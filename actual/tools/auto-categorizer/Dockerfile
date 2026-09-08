FROM node:20-slim

WORKDIR /app

# Install native compilation dependencies & locales for ONNX Runtime StringNormalizer
RUN apt-get update && apt-get install -y python3 make g++ locales locales-all \
    && sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen \
    && locale-gen \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

COPY package.json package-lock.json tsconfig.json ./

RUN npm ci

COPY src ./src
COPY README.md ./

RUN npm run build

EXPOSE 3080

CMD ["node", "dist/index.js"]
