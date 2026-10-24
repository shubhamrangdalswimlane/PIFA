# KIE Server (Drools 7.74) on Tomcat with PIFA's allocation rules deployed. Java is only the runtime of the official
# server: the repository holds DRL files and a Maven descriptor, no Java source.
FROM maven:3.9-eclipse-temurin-11 AS kjar
WORKDIR /build
# Build context is the repository root: the rule text lives once, in pifa_api/rules/allocation.drl.
COPY drools/pom.xml .
COPY drools/src ./src
COPY pifa_api/rules/allocation.drl ./src/main/resources/com/pifa/rules/allocation.drl
RUN mvn -q -B install -DskipTests
COPY drools/tomcat-libs-pom.xml /libs/pom.xml
RUN mvn -q -B -f /libs/pom.xml dependency:copy-dependencies -DoutputDirectory=/libs/jars

FROM tomcat:9.0-jdk11-temurin
ARG KIE=7.74.1.Final
RUN rm -rf /usr/local/tomcat/webapps/*
ADD https://repo1.maven.org/maven2/org/kie/server/kie-server/${KIE}/kie-server-${KIE}-webc.war /usr/local/tomcat/webapps/kie-server.war
COPY --from=kjar /libs/jars/ /usr/local/tomcat/lib/
COPY --from=kjar /root/.m2/repository/com/pifa /root/.m2/repository/com/pifa
COPY drools/tomcat-users.xml /usr/local/tomcat/conf/tomcat-users.xml
COPY drools/start.sh /start.sh
RUN chmod +x /start.sh
EXPOSE 8080
CMD ["/start.sh"]
