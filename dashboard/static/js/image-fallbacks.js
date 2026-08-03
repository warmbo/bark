/** Replace failed remote images with bundled, same-origin assets. */
function initImageFallbacks() {
    document.querySelectorAll('img[data-fallback-src]').forEach((image) => {
        const useFallback = () => {
            const fallback = image.dataset.fallbackSrc;
            if (!fallback || image.dataset.fallbackApplied === 'true') return;
            image.dataset.fallbackApplied = 'true';
            image.src = fallback;
        };
        image.addEventListener('error', useFallback, {once: true});
        if (image.complete && image.naturalWidth === 0) useFallback();
    });
}

document.addEventListener('DOMContentLoaded', initImageFallbacks);
