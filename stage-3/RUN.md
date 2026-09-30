# Running Tablekeeper (stage 2)

From this folder, build the image and start the service on port 8080:

```sh
docker build -t tablekeeper . && docker run --rm -e PORT=8080 -p 8080:8080 tablekeeper
```

The service is ready when `GET http://localhost:8080/health` returns `{"status": "ok"}`.

The browser screens are served on the same port: `/` (search and book a table), `/signup`,
`/login` and `/lookup` (find or cancel a booking), for example `http://localhost:8080/`.

It needs no network access at run time: the screens' fonts, styles and scripts and the time
zone data are all served from the image. It keeps all state in memory; load data with
`POST /_test/reset`.
