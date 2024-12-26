ffmpeg -i /dev/video0 -listen 1 -c:v libx264 -maxrate 100k -bufsize 2000k -g 50 -t 10 http://localhost:5000/test.mkv
