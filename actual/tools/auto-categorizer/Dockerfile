FROM node:20-slim

WORKDIR /app

# Install native compilation dependencies for SQLite / ONNX Runtime
RUN apt-get update && apt-get install -y python3 make g++ && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json tsconfig.json ./

RUN npm ci

COPY src ./src
COPY README.md ./

RUN npm run build

EXPOSE 3080

CMD ["node", "dist/index.js"]
