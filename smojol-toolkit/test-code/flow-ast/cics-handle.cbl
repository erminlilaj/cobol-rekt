       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICS-HANDLE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           01  WS-MSG PIC X(20) VALUE "HELLO".
       PROCEDURE DIVISION.
       MAIN-PARA.
           EXEC CICS HANDLE CONDITION
                ERROR(ERROR-HANDLER)
                MAPFAIL(MAP-HANDLER)
           END-EXEC
           EXEC CICS HANDLE AID
                CLEAR(CLEAR-HANDLER)
           END-EXEC
           EXEC CICS HANDLE ABEND
                LABEL(ABEND-HANDLER)
           END-EXEC
           EXEC CICS LINK PROGRAM('PAYPGM')
                COMMAREA(WS-MSG)
           END-EXEC
           EXEC CICS SEND MAP('PAYMAP')
                MAPSET('PAYMAPS')
           END-EXEC
           EXEC CICS RETURN TRANSID('PAYT')
           END-EXEC
           GOBACK.
       ERROR-HANDLER.
           DISPLAY WS-MSG.
       MAP-HANDLER.
           DISPLAY WS-MSG.
       CLEAR-HANDLER.
           DISPLAY WS-MSG.
       ABEND-HANDLER.
           DISPLAY WS-MSG.
