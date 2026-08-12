*=== lusrbl =========================================================*
*
*     Second user variable of a USRBIN of type 8: which airway region.
*
*     1 bronchial (BB, generations 1 to 8), 2 bronchiolar (bb, 9 to 16),
*     0 outside. The two have different layer counts and different
*     target volumes, so they must be kept apart.
*
*=====================================================================*
      INTEGER FUNCTION LUSRBL ( IJ, PCONTR, XA, YA, ZA, MREG, LATCLL,
     &                          ICALL )

      INCLUDE 'dblprc.inc'
      INCLUDE 'dimpar.inc'
      INCLUDE 'iounit.inc'

      DOUBLE PRECISION PCONTR, XA, YA, ZA
      INTEGER IJ, MREG, LATCLL, ICALL, AWLAYR

      LUSRBL = AWLAYR ( XA, YA, ZA ) / 100
      RETURN
      END
