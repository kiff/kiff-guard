#!/bin/bash
# Start kiff-decide + ap-app detached so they survive the SSH session.
cd /home/ec2-user/duplicate-payment-guard || exit 1
pkill -f kiff-decide 2>/dev/null
pkill -f 'ap-app/server' 2>/dev/null
sleep 1
nohup ./kiff-decide/kiff-decide -addr=:8081 >/tmp/kiff.log 2>&1 </dev/null &
nohup env KIFF_BASE_URL=http://localhost:8081 node ap-app/server.js >/tmp/apapp.log 2>&1 </dev/null &
sleep 3
echo "started; processes:"
ps aux | grep -E 'kiff-decide|ap-app/server' | grep -v grep | awk '{print $11, $12, $13}'
