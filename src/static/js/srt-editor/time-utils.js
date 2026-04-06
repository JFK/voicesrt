/** Pure time formatting/parsing utilities — no Alpine `this` dependency. */

export function formatTimeFull(seconds) {
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    var s = seconds % 60;
    return h.toString().padStart(2, '0') + ':' + m.toString().padStart(2, '0') + ':' + s.toFixed(1).padStart(4, '0');
}

export function formatTime(seconds) {
    var h = Math.floor(seconds / 3600);
    var m = Math.floor((seconds % 3600) / 60);
    var s = Math.floor(seconds % 60);
    return h.toString().padStart(2, '0') + ':' + m.toString().padStart(2, '0') + ':' + s.toString().padStart(2, '0');
}

export function parseTime(str) {
    var parts = str.split(':');
    var val;
    if (parts.length === 3) {
        val = parseInt(parts[0]) * 3600 + parseInt(parts[1]) * 60 + parseFloat(parts[2]);
    } else if (parts.length === 2) {
        val = parseInt(parts[0]) * 60 + parseFloat(parts[1]);
    } else {
        val = parseFloat(str);
    }
    return isNaN(val) ? null : val;
}

export function validateTimes(segments) {
    var errors = [];
    for (var i = 0; i < segments.length; i++) {
        var seg = segments[i];
        if (seg.start >= seg.end) {
            errors.push('#' + (i + 1) + ': start >= end');
        }
        if (i > 0 && seg.start < segments[i - 1].end) {
            errors.push('#' + (i + 1) + ': overlaps with #' + i);
        }
    }
    return errors;
}

export function autoResize(el) {
    if (!el) return;
    el.style.height = '0';
    el.style.height = Math.max(el.scrollHeight, 48) + 'px';
}
