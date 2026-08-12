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
      CHARACTER*250 CHSTEM
      LOGICAL LFIRST
      SAVE LFIRST
      DATA LFIRST / .TRUE. /

      IF ( LFIRST ) THEN
         CHSTEM = ' '
         OPEN ( UNIT = 88, FILE = 'airway.stem', STATUS = 'OLD',
     &          ERR = 10 )
         READ ( 88, '(A)', END = 10 ) CHSTEM
         CLOSE ( 88 )
 10      CONTINUE
         IF ( CHSTEM .EQ. ' ' ) THEN
            OPEN ( UNIT = 88, FILE = '../airway.stem', STATUS = 'OLD',
     &             ERR = 20 )
            READ ( 88, '(A)', END = 20 ) CHSTEM
            CLOSE ( 88 )
 20         CONTINUE
         END IF
         IF ( CHSTEM .EQ. ' ' ) CALL GETENV ( 'AIRWAY_DATA', CHSTEM )
         IF ( CHSTEM .EQ. ' ' ) THEN
            WRITE ( LUNERR, * ) ' AIRWAY: no airway.stem found'
            CALL FLABRT ( 'MUSRBR', 'airway.stem' )
         END IF
         CALL AWINIT ( CHSTEM )
         LFIRST = .FALSE.
      END IF

      IL = AWLAYR ( XA, YA, ZA )
      MUSRBR = MOD ( IL, 100 )
      RETURN
      END
