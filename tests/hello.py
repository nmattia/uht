from uht import HTTPServer

app = HTTPServer()

@app.route("/")
async def index(req, resp):
    await resp.send(b"Hello, world!")

app.run(host="0.0.0.0", port=80)
