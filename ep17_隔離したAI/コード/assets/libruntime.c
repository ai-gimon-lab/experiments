#include <stdio.h>
/* agent-runtime compat layer */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <string.h>
#include <stdlib.h>
#include <sys/utsname.h>

static void fill(char *dst, size_t n, const char *s) { strncpy(dst, s, n - 1); dst[n - 1] = 0; }

int uname(struct utsname *buf) {
    int (*real)(struct utsname *) = dlsym(RTLD_NEXT, "uname");
    int r = real ? real(buf) : -1;
    if (r == 0) {
        const char *rel = NULL;
        const char *ver = NULL;
        static char frel[128], fver[256];
        {
            FILE *f = fopen("/etc/agent-runtime/compat.conf", "r");
            if (f) {
                if (fgets(frel, sizeof frel, f)) { frel[strcspn(frel, "\n")] = 0; rel = frel; }
                if (fgets(fver, sizeof fver, f)) { fver[strcspn(fver, "\n")] = 0; ver = fver; }
                fclose(f);
            }
        }
        if (rel) fill(buf->release, sizeof buf->release, rel);
        if (ver) fill(buf->version, sizeof buf->version, ver);
    }
    return r;
}
