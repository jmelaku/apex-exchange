FROM debian:bookworm-slim AS build
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY src/main.cpp .
RUN g++ -std=c++20 -O2 -pthread -Wall -Wextra -Wpedantic main.cpp -o apex-simulator
FROM debian:bookworm-slim
COPY --from=build /src/apex-simulator /usr/local/bin/apex-simulator
USER nobody
ENTRYPOINT ["apex-simulator"]
