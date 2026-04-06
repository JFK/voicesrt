/**
 * JobStatusClient — real-time job status via SSE with polling fallback.
 *
 * Usage:
 *   const client = new JobStatusClient(jobId, {
 *       onStatus: function(data) { ... },
 *       onComplete: function(data) { ... },
 *       onError: function(err) { ... },
 *       statusUrl: '/api/jobs/' + jobId + '/status',  // polling fallback
 *   });
 *   // Later:
 *   client.destroy();
 */
window.JobStatusClient = function (jobId, options) {
    options = options || {};
    var self = {
        _es: null,
        _pollTimer: null,
        _retryCount: 0,
        _maxRetries: options.maxRetries || 5,
        _destroyed: false,
        _onStatus: options.onStatus || function () {},
        _onComplete: options.onComplete || function () {},
        _onError: options.onError || function () {},
        _statusUrl: options.statusUrl || ('/api/jobs/' + jobId + '/status'),
        _streamUrl: '/api/jobs/' + jobId + '/stream',
    };

    function handleData(data) {
        if (self._destroyed) return;
        self._retryCount = 0;
        // Normalize: the polling endpoint returns `error_message` while SSE
        // events use `detail`. Callers should always read `data.detail`.
        if (data && data.error_message && !data.detail) {
            data.detail = data.error_message;
        }
        self._onStatus(data);
        if (data.status === 'completed' || data.status === 'failed') {
            self._onComplete(data);
            destroy();
        }
    }

    function connectSSE() {
        if (self._destroyed) return;
        try {
            self._es = new EventSource(self._streamUrl);
            self._es.onmessage = function (event) {
                try {
                    var data = JSON.parse(event.data);
                    handleData(data);
                } catch (e) {
                    console.error('JobStatusClient: parse error', e);
                }
            };
            self._es.onerror = function () {
                if (self._destroyed) return;
                self._es.close();
                self._es = null;
                self._retryCount++;
                if (self._retryCount <= self._maxRetries) {
                    var delay = Math.min(1000 * Math.pow(2, self._retryCount - 1), 16000);
                    setTimeout(connectSSE, delay);
                } else {
                    startPolling();
                }
            };
        } catch (e) {
            startPolling();
        }
    }

    function startPolling() {
        if (self._destroyed || self._pollTimer) return;
        self._pollTimer = setInterval(function () {
            fetch(self._statusUrl)
                .then(function (res) { return res.json(); })
                .then(function (data) {
                    handleData(data);
                })
                .catch(function (err) {
                    self._onError(err);
                });
        }, 2000);
    }

    function destroy() {
        self._destroyed = true;
        if (self._es) {
            self._es.close();
            self._es = null;
        }
        if (self._pollTimer) {
            clearInterval(self._pollTimer);
            self._pollTimer = null;
        }
    }

    // Start SSE connection
    connectSSE();

    return { destroy: destroy };
};
