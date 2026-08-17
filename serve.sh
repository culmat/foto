echo "LAN: http://$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo localhost):8000"
python3 -m http.server 8000 --bind 0.0.0.0
