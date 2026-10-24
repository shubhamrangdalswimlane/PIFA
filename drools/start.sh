#!/bin/sh
# Starts Tomcat with the KIE Server, then deploys the PIFA rules as container "pifa" and keeps Tomcat in the foreground.
USER="${KIE_USER:-pifa}"; PASS="${KIE_PASSWORD:?KIE_PASSWORD is required}"
sed -i "s|\${KIE_USER}|$USER|; s|\${KIE_PASSWORD}|$PASS|" /usr/local/tomcat/conf/tomcat-users.xml
export CATALINA_OPTS="-Xmx700m -Dorg.kie.server.id=pifa -Dorg.kie.server.user=$USER -Dorg.kie.server.pwd=$PASS \
 -Dorg.kie.server.location=http://localhost:8080/kie-server/services/rest/server -Dkie.maven.offline.force=true \
 -Dorg.jbpm.server.ext.disabled=true -Dorg.jbpm.ui.server.ext.disabled=true -Dorg.optaplanner.server.ext.disabled=true \
 -Dorg.kie.prometheus.server.ext.disabled=true -Dorg.kie.scenariosimulation.server.ext.disabled=true -Dorg.kie.dmn.server.ext.disabled=true"
catalina.sh run &
PID=$!
URL=http://localhost:8080/kie-server/services/rest/server
until curl -fs -u "$USER:$PASS" "$URL" >/dev/null 2>&1; do sleep 3; done
curl -s -u "$USER:$PASS" -X PUT -H 'Content-Type: application/json' "$URL/containers/pifa" \
  -d '{"container-id":"pifa","release-id":{"group-id":"com.pifa","artifact-id":"rules","version":"1.0.0"}}'
echo
wait $PID
