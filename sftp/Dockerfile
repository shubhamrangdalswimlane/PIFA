# SFTP for PIFA (Render private service). Key-only, chrooted user `pifa`.
# Persistent disk is mounted at /home: user files live in /home/pifa/files,
# host keys in /home/.hostkeys (outside the chroot) so they survive redeploys.
FROM atmoz/sftp:alpine
COPY entrypoint.sh /pifa-entrypoint.sh
RUN chmod +x /pifa-entrypoint.sh
EXPOSE 22
ENTRYPOINT ["/pifa-entrypoint.sh"]
