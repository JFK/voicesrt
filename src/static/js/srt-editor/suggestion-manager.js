/** AI suggestion request/accept/dismiss — uses Alpine `this`. */

export function createSuggestionManager(jobId) {
    return {
        async requestSuggestion(idx) {
            this.suggesting[idx] = true;
            try {
                var res = await fetch('/api/jobs/' + jobId + '/segments/' + idx + '/suggest', {
                    method: 'POST',
                });
                if (!res.ok) throw new Error('Suggestion failed');
                var data = await res.json();
                this.suggestions[idx] = data;
            } catch (e) {
                console.error(e);
            } finally {
                this.suggesting[idx] = false;
            }
        },

        acceptSuggestion(idx) {
            if (this.suggestions[idx]) {
                this.segments[idx].text = this.suggestions[idx].text;
                this.suggestions = Object.assign({}, this.suggestions, {[idx]: null});
                this.debounceSave();
            }
        },

        dismissSuggestion(idx) {
            this.suggestions = Object.assign({}, this.suggestions, {[idx]: null});
        },
    };
}
