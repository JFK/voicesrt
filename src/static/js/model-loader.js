/**
 * ModelLoader — shared utility for fetching and caching available AI models.
 *
 * Usage (Alpine.js):
 *   const data = await ModelLoader.load();
 *   const models = ModelLoader.getModels('openai');
 *
 * Usage (vanilla JS):
 *   ModelLoader.load().then(data => { ... });
 */
window.ModelLoader = (function () {
    let _cache = null;
    let _promise = null;

    return {
        /** Fetch model data from API. Returns cached data on subsequent calls. */
        load() {
            if (_cache) return Promise.resolve(_cache);
            if (_promise) return _promise;
            _promise = fetch('/api/settings/available-models')
                .then(function (res) {
                    if (!res.ok) throw new Error('HTTP ' + res.status);
                    return res.json();
                })
                .then(function (data) {
                    _cache = data;
                    _promise = null;
                    return data;
                })
                .catch(function (e) {
                    _promise = null;
                    console.error('ModelLoader: failed to load models', e);
                    // Do not poison the cache — next call will retry.
                    return { available: {}, configured: {}, has_key: {} };
                });
            return _promise;
        },

        /** Get list of available models for a provider. */
        getModels(provider) {
            return _cache?.available?.[provider] || [];
        },

        /** Get the configured (default) model for a provider. */
        getConfigured(provider) {
            return _cache?.configured?.[provider] || '';
        },

        /** Check if the user has an API key configured for a provider. */
        hasKey(provider) {
            return _cache?.has_key?.[provider] || false;
        },

        /** Get the full cached data object. */
        getData() {
            return _cache;
        },

        /** Clear cache so next load() re-fetches from API. */
        invalidate() {
            _cache = null;
            _promise = null;
        },
    };
})();
