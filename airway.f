*=== airway =========================================================*
*
*     ICRP-145 bronchial airway model for FLUKA.
*
*     ICRP distributes the airway tree separately from the tetrahedral
*     mesh, as MRCP_<sex>.lung and MRCP_<sex>.lungDiam, because the
*     epithelial layers are a few micrometres thick and no mesh of that
*     body could resolve them. Geant4 puts them in a parallel world.
*     FLUKA has no parallel world, so they are not geometry here: the
*     layer a deposit falls in is computed at scoring time and returned
*     to a USRBIN of type 8 through MUSRBR.
*
*     The tree is a heap: node I hangs off node I/2. Each branch is a
*     cone tapering from its parent's diameter to its own, and each node
*     carries a sphere of its own diameter, so the union is continuous
*     across the bifurcations. Ten nested layers for the bronchial
*     region BB, eight for the bronchiolar region bb; the gap between
*     layer L and layer L+1 is the target tissue.
*
*     AWINIT reads the two files and sorts the branches into a uniform
*     grid. AWLAYR answers, for one point, which layer it is in. Without
*     the grid every deposit would be tested against 39399 branches.
*
*=====================================================================*
      SUBROUTINE AWINIT ( CHFIL )

      INCLUDE 'dblprc.inc'
      INCLUDE 'dimpar.inc'
      INCLUDE 'iounit.inc'
      INCLUDE 'airway.inc'

      CHARACTER*(*) CHFIL
      CHARACTER*250 CHLUNG, CHDIAM
      LOGICAL LHERE
      DOUBLE PRECISION XX, YY, ZZ, DTMP
      INTEGER IDUM, ICHK, I, J, L, IG, IP, N, IX, IY, IZ
      LOGICAL LEX ( MXNODE )
      DOUBLE PRECISION PX ( MXNODE ), PY ( MXNODE ), PZ ( MXNODE )

      CHLUNG = CHFIL(1:LNBLNK(CHFIL))//'.lung'
      CHDIAM = CHFIL(1:LNBLNK(CHFIL))//'.lungDiam'
*     The stem is relative to the case directory, but rfluka works in a
*     subdirectory of it, so from here the path needs one more level up.
*     Try it as given first, for the case where FLUKA is run in the case
*     directory itself.
      INQUIRE ( FILE = CHLUNG, EXIST = LHERE )
      IF ( .NOT. LHERE ) THEN
         CHLUNG = '../'//CHFIL(1:LNBLNK(CHFIL))//'.lung'
         CHDIAM = '../'//CHFIL(1:LNBLNK(CHFIL))//'.lungDiam'
      END IF

*     ---- the tree ----------------------------------------------------
      OPEN ( UNIT = 87, FILE = CHLUNG, STATUS = 'OLD', ERR = 9001 )
      NNODE = 0
      DO I = 1, MXNODE
         READ ( 87, *, END = 100 ) IDUM, XX, YY, ZZ, ICHK
         NNODE = NNODE + 1
         PX ( NNODE ) = XX
         PY ( NNODE ) = YY
         PZ ( NNODE ) = ZZ
         LEX ( NNODE ) = ICHK .NE. 0
      END DO
 100  CONTINUE
      CLOSE ( 87 )

*     ---- layer diameters, metres in the file, centimetres here -------
      OPEN ( UNIT = 87, FILE = CHDIAM, STATUS = 'OLD', ERR = 9002 )
      DO I = 1, 8
         READ ( 87, * ) ( DIAM ( I, J ), J = 1, 10 )
         NLAY ( I ) = 10
      END DO
      DO I = 9, 16
         READ ( 87, * ) ( DIAM ( I, J ), J = 1, 8 )
         NLAY ( I ) = 8
      END DO
      CLOSE ( 87 )
      DO J = 1, 8
         DIAM ( 17, J ) = DIAM ( 16, J )
      END DO
      NLAY ( 17 ) = 8
      DO I = 1, 17
         DO J = 1, 10
            DIAM ( I, J ) = DIAM ( I, J ) * 100.0D+00
         END DO
      END DO

*     ---- branches: node I to its parent I/2 --------------------------
      NSEG = 0
      DO I = 3, NNODE
         IF ( .NOT. LEX ( I ) ) GO TO 200
         IP = ( I - 1 ) / 2 + 1
         IG = 1
         N  = I - 1
 150     CONTINUE
         IF ( N .GE. 2 ) THEN
            N  = N / 2
            IG = IG + 1
            GO TO 150
         END IF
*        IG is the generation of node I, 1-based for the DIAM table
         IF ( NLAY ( IG ) .NE. NLAY ( MAX ( IG - 1, 1 ) ) ) GO TO 200
         NSEG = NSEG + 1
         IF ( NSEG .GT. MXSEG ) GO TO 9004
         SGX1 ( NSEG ) = PX ( IP )
         SGY1 ( NSEG ) = PY ( IP )
         SGZ1 ( NSEG ) = PZ ( IP )
         SGX2 ( NSEG ) = PX ( I )
         SGY2 ( NSEG ) = PY ( I )
         SGZ2 ( NSEG ) = PZ ( I )
         SGGEN ( NSEG ) = IG
 200     CONTINUE
      END DO

*     ---- bounding box and grid ---------------------------------------
      GXMIN = PX ( 1 )
      GXMAX = PX ( 1 )
      GYMIN = PY ( 1 )
      GYMAX = PY ( 1 )
      GZMIN = PZ ( 1 )
      GZMAX = PZ ( 1 )
      DO I = 1, NSEG
         GXMIN = MIN ( GXMIN, SGX1 ( I ), SGX2 ( I ) )
         GXMAX = MAX ( GXMAX, SGX1 ( I ), SGX2 ( I ) )
         GYMIN = MIN ( GYMIN, SGY1 ( I ), SGY2 ( I ) )
         GYMAX = MAX ( GYMAX, SGY1 ( I ), SGY2 ( I ) )
         GZMIN = MIN ( GZMIN, SGZ1 ( I ), SGZ2 ( I ) )
         GZMAX = MAX ( GZMAX, SGZ1 ( I ), SGZ2 ( I ) )
      END DO
      GXMIN = GXMIN - ONEONE
      GYMIN = GYMIN - ONEONE
      GZMIN = GZMIN - ONEONE
      GXMAX = GXMAX + ONEONE
      GYMAX = GYMAX + ONEONE
      GZMAX = GZMAX + ONEONE
      GCELL = GRDCEL
      NGX = INT ( ( GXMAX - GXMIN ) / GCELL ) + 1
      NGY = INT ( ( GYMAX - GYMIN ) / GCELL ) + 1
      NGZ = INT ( ( GZMAX - GZMIN ) / GCELL ) + 1

      IF ( NGX * NGY * NGZ .GT. MXCELL ) GO TO 9005
      DO I = 1, NGX * NGY * NGZ
         IHEAD ( I ) = 0
      END DO
*     every cell the branch's bounding box touches gets the branch, so
*     AWLAYR need only look in the cell holding the point
      NLIST = 0
      DO I = 1, NSEG
         DTMP = HLFHLF * DIAM ( MAX ( SGGEN ( I ) - 1, 1 ), 1 )
         DO IX = ICELL ( MIN ( SGX1(I), SGX2(I) ) - DTMP, GXMIN, NGX ),
     &           ICELL ( MAX ( SGX1(I), SGX2(I) ) + DTMP, GXMIN, NGX )
         DO IY = ICELL ( MIN ( SGY1(I), SGY2(I) ) - DTMP, GYMIN, NGY ),
     &           ICELL ( MAX ( SGY1(I), SGY2(I) ) + DTMP, GYMIN, NGY )
         DO IZ = ICELL ( MIN ( SGZ1(I), SGZ2(I) ) - DTMP, GZMIN, NGZ ),
     &           ICELL ( MAX ( SGZ1(I), SGZ2(I) ) + DTMP, GZMIN, NGZ )
            N = IX + NGX * ( IY - 1 ) + NGX * NGY * ( IZ - 1 )
            NLIST = NLIST + 1
            IF ( NLIST .GT. MXLIST ) GO TO 9003
            LSEG ( NLIST ) = I
            LNXT ( NLIST ) = IHEAD ( N )
            IHEAD ( N ) = NLIST
         END DO
         END DO
         END DO
      END DO

      WRITE ( LUNOUT, * ) ' AIRWAY: ', NSEG, ' branches, grid ',
     &                      NGX, NGY, NGZ, ' entries ', NLIST
      RETURN

 9001 WRITE ( LUNERR, * ) ' AIRWAY: cannot open ', CHLUNG
      CALL FLABRT ( 'AWINIT', 'lung file' )
 9002 WRITE ( LUNERR, * ) ' AIRWAY: cannot open ', CHDIAM
      CALL FLABRT ( 'AWINIT', 'lungDiam file' )
 9003 WRITE ( LUNERR, * ) ' AIRWAY: MXLIST too small'
      CALL FLABRT ( 'AWINIT', 'grid overflow' )
 9004 WRITE ( LUNERR, * ) ' AIRWAY: more branches than MXSEG =', MXSEG
      CALL FLABRT ( 'AWINIT', 'too many branches' )
 9005 WRITE ( LUNERR, * ) ' AIRWAY: grid ', NGX * NGY * NGZ,
     &                     ' cells exceeds MXCELL =', MXCELL
      CALL FLABRT ( 'AWINIT', 'MXCELL too small' )
      END

*=== awlayr =========================================================*
*
*     Which epithelial layer holds (X,Y,Z)?
*
*     Returns 0 outside the airways, otherwise 100*IBAND + LAYER, where
*     IBAND is 1 for the bronchial region and 2 for the bronchiolar one
*     and LAYER counts inwards from the outer surface. The point is in
*     layer L when it lies inside the tube at L but not inside the one
*     at L+1.
*
*=====================================================================*
      INTEGER FUNCTION AWLAYR ( X, Y, Z )

      INCLUDE 'dblprc.inc'
      INCLUDE 'dimpar.inc'
      INCLUDE 'airway.inc'

      DOUBLE PRECISION X, Y, Z
      DOUBLE PRECISION AX, AY, AZ, BX, BY, BZ, TT, DD, RR, D2, RA, RB
      INTEGER IX, IY, IZ, IC, IL, I, IG, LMIN, IBAND

      AWLAYR = 0
      IF ( X .LT. GXMIN .OR. X .GT. GXMAX ) RETURN
      IF ( Y .LT. GYMIN .OR. Y .GT. GYMAX ) RETURN
      IF ( Z .LT. GZMIN .OR. Z .GT. GZMAX ) RETURN
      IX = ICELL ( X, GXMIN, NGX )
      IY = ICELL ( Y, GYMIN, NGY )
      IZ = ICELL ( Z, GZMIN, NGZ )
      IC = IHEAD ( IX + NGX * ( IY - 1 ) + NGX * NGY * ( IZ - 1 ) )

      LMIN  = 0
      IBAND = 0
 10   CONTINUE
      IF ( IC .EQ. 0 ) GO TO 90
      I  = LSEG ( IC )
      IG = SGGEN ( I )
      AX = SGX1 ( I )
      AY = SGY1 ( I )
      AZ = SGZ1 ( I )
      BX = SGX2 ( I ) - AX
      BY = SGY2 ( I ) - AY
      BZ = SGZ2 ( I ) - AZ
      DD = BX * BX + BY * BY + BZ * BZ
      IF ( DD .LE. ZERZER ) GO TO 80
      TT = ( ( X - AX ) * BX + ( Y - AY ) * BY + ( Z - AZ ) * BZ ) / DD
      TT = MAX ( ZERZER, MIN ( ONEONE, TT ) )
      D2 = ( X - AX - TT * BX ) ** 2 + ( Y - AY - TT * BY ) ** 2
     &   + ( Z - AZ - TT * BZ ) ** 2
*     innermost layer this branch puts the point in
      DO IL = NLAY ( IG ), 1, -1
         RA = HLFHLF * DIAM ( MAX ( IG - 1, 1 ), IL )
         RB = HLFHLF * DIAM ( IG, IL )
         RR = RA + TT * ( RB - RA )
         IF ( D2 .LE. RR * RR ) THEN
            IF ( IL .GT. LMIN ) THEN
               LMIN  = IL
               IBAND = 1
               IF ( NLAY ( IG ) .EQ. 8 ) IBAND = 2
            END IF
            GO TO 80
         END IF
      END DO
 80   CONTINUE
      IC = LNXT ( IC )
      GO TO 10
 90   CONTINUE
      IF ( LMIN .GT. 0 ) AWLAYR = 100 * IBAND + LMIN
      RETURN
      END

*=== icell ==========================================================*
      INTEGER FUNCTION ICELL ( V, VMIN, NV )
      INCLUDE 'dblprc.inc'
      INCLUDE 'airway.inc'
      DOUBLE PRECISION V, VMIN
      INTEGER NV
      ICELL = INT ( ( V - VMIN ) / GCELL ) + 1
      ICELL = MAX ( 1, MIN ( NV, ICELL ) )
      RETURN
      END
