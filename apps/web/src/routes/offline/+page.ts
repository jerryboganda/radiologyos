// Static HTML with no client JS: it must render from the service-worker cache
// with no network (no __data.json fetch). The theme script in app.html still runs.
export const prerender = true;
export const csr = false;
