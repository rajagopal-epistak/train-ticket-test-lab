#!/usr/bin/env bash
# Run Maven for one service module inside the official maven Java 8 image.
# The podman VM mounts no host folders, so the needed sources are streamed in over tar.
# Usage: hack/lab/mvn.sh <module> <maven args...>
#   e.g. hack/lab/mvn.sh ts-order-other-service test -Dtest=OrderOtherServiceImplF12Test -Dsurefire.failIfNoSpecifiedTests=false
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
module="$1"
shift
git ls-files -z --cached --others --exclude-standard -- pom.xml '*/pom.xml' ts-common "$module" \
  | COPYFILE_DISABLE=1 tar --no-mac-metadata --no-xattrs --null -T - -cf - \
  | podman run -i --rm -v tt-m2:/root/.m2 docker.io/library/maven:3.9-eclipse-temurin-8 \
      sh -c 'mkdir /src && cd /src && tar -xf - && mvn -B -pl "$0" -am "$@"' "$module" "$@"
