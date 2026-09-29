# Running Tablekeeper (stage 1)

From this folder, build the image and start the service on port 8080:

```sh
docker build -t tablekeeper . && docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper
```

The service is ready when `GET http://localhost:8080/health` returns `{"status": "ok"}`.
It needs no network access at run time and keeps all state in memory; load data with
`POST /_test/reset`.
