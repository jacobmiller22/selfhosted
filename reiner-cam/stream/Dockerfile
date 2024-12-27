FROM ubuntu

RUN apt-get update && apt-get install -y \
	motion \
	ffmpeg

CMD ["ffmpeg", "-i", "/dev/video0", "-listen", "1", "-c:v", "libx264", "-maxrate", "100k", "-preset", "fast", "-bufsize", "2000k", "-g", "50", "rtmp://mediamtx:1935/test"]
