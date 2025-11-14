from server import Server

# 서버 실행
if __name__ == "__main__":
    server = Server()
    server.run(host="0.0.0.0", port=8000)
