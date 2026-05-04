       IDENTIFICATION DIVISION.
       PROGRAM-ID. NONMON.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  ROOT-REC.
           03  PART-A.
               05  GROUP-A.
                   07  FIELD-A        PIC X(1).
                   07  FIELD-B        PIC X(1).
               04  PART-B.
                   05  FIELD-C        PIC X(1).
       01  EMPTY-GROUP.
       PROCEDURE DIVISION.
           GOBACK.
