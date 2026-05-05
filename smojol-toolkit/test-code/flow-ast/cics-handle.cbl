       IDENTIFICATION DIVISION.
       PROGRAM-ID. CICS-HANDLE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           01  WS-MSG PIC X(20) VALUE "HELLO".
           01  WS-PROGRAM PIC X(08).
           01  WS-RESP PIC S9(8) COMP.
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
           MOVE 'DYNCICS' TO WS-PROGRAM
           EXEC CICS LINK PROGRAM(WS-PROGRAM)
                COMMAREA(WS-MSG)
                LENGTH(20)
                RESP(WS-RESP)
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
