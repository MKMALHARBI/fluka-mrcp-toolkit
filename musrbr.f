*=== musrbr =========================================================*
*
*     First user variable of a USRBIN of type 8: the epithelial layer.
*
*     Returns 0 when the deposit is outside the airways, otherwise the
*     layer counted inwards from the outer surface, 1 to 10 in the
*     bronchial region and 1 to 8 in the bronchiolar one. LUSRBL says
*     which of the two it is.
*
*     The tree is loaded on the first call. The stem of the two ICRP
*     files, for instance ../../phantom/MRCP_AM/MRCP_AM, is read from a
*     one-line file airway.stem that make_examples.py leaves beside the
*     input. rfluka runs in a subdirectory of the case directory, so the
*     file is one level up; the current directory is tried first for the
*     case where FLUKA is run by hand.
*
*=====================================================================*
      INTEGER FUNCTION MUSRBR ( IJ, PCONTR, XA, YA, ZA, MREG, LATCLL,
     &                          ICALL )

      INCLUDE 'dblprc.inc'
      INCLUDE 'dimpar.inc'
      INCLUDE 'iounit.inc'

      DOUBLE PRECISION PCONTR, XA, YA, ZA
      INTEGER IJ, MREG, LATCLL, ICALL, AWLAYR, IL

      CALL AWENSR
      IL = AWLAYR ( XA, YA, ZA )
      MUSRBR = MOD ( IL, 100 )
      RETURN
      END
