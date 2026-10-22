# ---- build: compile, run all JUnit tests, produce the shaded jar ----
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY pom.xml .
RUN mvn -B -q dependency:go-offline || true
COPY src ./src
RUN mvn -B package

# ---- runtime ----
FROM eclipse-temurin:21-jre
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=build /src/target/pifa-rules.jar /app/pifa-rules.jar
USER 10001:10001
ENV PORT=8080 \
    JAVA_OPTS="-XX:MaxRAMPercentage=75 -XX:+UseSerialGC"
EXPOSE 8080
# App reads PORT itself (Render injects it).
ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/pifa-rules.jar"]
