*=== airway.inc =====================================================*
*
*     Shared storage for the ICRP-145 bronchial airway model.
*
*     MXNODE is the size of the tree ICRP distributes, 2**16. MXSEG is
*     how many of those branches actually exist, 39399 in the male
*     phantom, rounded up. MXLIST is the grid index: a branch is listed
*     once for every cell its bounding box touches, so it runs to a few
*     times MXSEG.
*
*=====================================================================*
      INTEGER MXNODE, MXSEG, MXCELL, MXLIST
      PARAMETER ( MXNODE = 65536 )
      PARAMETER ( MXSEG  = 50000 )
      PARAMETER ( MXCELL = 4000000 )
      PARAMETER ( MXLIST = 2000000 )

      DOUBLE PRECISION GRDCEL
      PARAMETER ( GRDCEL = 0.25D+00 )

      DOUBLE PRECISION SGX1, SGY1, SGZ1, SGX2, SGY2, SGZ2, DIAM,
     &                 GXMIN, GXMAX, GYMIN, GYMAX, GZMIN, GZMAX, GCELL
      INTEGER SGGEN, NLAY, IHEAD, LSEG, LNXT,
     &        NNODE, NSEG, NGX, NGY, NGZ, NLIST

      COMMON / AIRWAR / SGX1 ( MXSEG ), SGY1 ( MXSEG ), SGZ1 ( MXSEG ),
     &                  SGX2 ( MXSEG ), SGY2 ( MXSEG ), SGZ2 ( MXSEG ),
     &                  DIAM ( 17, 10 ),
     &                  GXMIN, GXMAX, GYMIN, GYMAX, GZMIN, GZMAX, GCELL
      COMMON / AIRWAI / SGGEN ( MXSEG ), NLAY ( 17 ),
     &                  IHEAD ( MXCELL ), LSEG ( MXLIST ),
     &                  LNXT ( MXLIST ),
     &                  NNODE, NSEG, NGX, NGY, NGZ, NLIST
      SAVE / AIRWAR /
      SAVE / AIRWAI /
