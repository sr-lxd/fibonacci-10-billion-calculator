/* Compile against the *packaged matching header*, without linking a GMP DLL. */
#include <stdio.h>
#ifdef PROBE_MPIR
#include <mpir.h>
#else
#include <gmp.h>
#endif
int main(void) {
    printf("{\"limb_bytes\":%u,\"mp_size_bytes\":%u,\"mp_bitcnt_bytes\":%u,\"ulong_bytes\":%u,\"pointer_bytes\":%u,\"gmp_major\":%d,\"gmp_minor\":%d,\"gmp_patch\":%d}\n",
           (unsigned)sizeof(mp_limb_t),(unsigned)sizeof(mp_size_t),(unsigned)sizeof(mp_bitcnt_t),
           (unsigned)sizeof(unsigned long),(unsigned)sizeof(void *),
           __GNU_MP_VERSION,__GNU_MP_VERSION_MINOR,__GNU_MP_VERSION_PATCHLEVEL);
    return 0;
}
