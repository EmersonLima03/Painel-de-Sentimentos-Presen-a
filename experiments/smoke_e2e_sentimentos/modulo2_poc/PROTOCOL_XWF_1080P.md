# PROTOCOL — XWF-1080P (câmera de laboratório)

**Papel:** provar enrollment/reconhecimento (mecanismo).  
**Não é** validação definitiva da sala / VIP-5440-IA.

## O que a XWF responde

- Pipeline detect → quality → embed → match TEMP  
- Distância / pose / óculos / UNKNOWN / multi-rosto no POC  
- Metodologia de teste da Estratégia A  

## O que fica para a VIP-5440-IA

- FOV real de sala ~36 m²  
- Cobertura / zonas cegas / altura de instalação  
- Pixels por rosto nas carteiras  
- Iluminação de sala / RTSP  
- Multi-aluno em densidade escolar  
- Sobreposição multi-câmera  

## Índice USB

Descobrir com `scripts/list_webcams.py`. Referência lab: index **2**, 1920×1080 (`config.yaml` `cam-web`).

## Execução

Seguir `RUNBOOK_TESTES_XWF.md`.
