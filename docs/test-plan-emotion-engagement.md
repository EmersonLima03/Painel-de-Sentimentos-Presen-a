# Plano de teste manual — emoção / engajamento / sinais

Ver também `docs/test_5_people.md`.

## Cenários mínimos

Para cada: resultado esperado | obtido | confiança | qualidade | latência | FP | FN | obs.

1. Pessoa olhando para frente
2. Olhar breve para baixo
3. Pessoa escrevendo
4. Olhar baixo prolongado
5. Celular na mesa sem uso → `phone_visible`, não `possible`
6. Segurando celular
7. Olhando celular vários segundos → `possible`/`probable` (nunca auto-confirmed)
8. Piscadas normais
9. Olhos fechados 2s → sem sonolência
10. Sonolência simulada >10s
11. Sorriso / neutro
12. Oclusão parcial / distante / low light
13. 8 pessoas simultâneas (métricas gate)
14. Cruzamentos / saída-retorno
15. Queda RTSP / restart app
16. Sessão completa + revisão FP + sync mock LXP

## Critério 8 pessoas (mensurável)

Registrar: estabilidade tracks, ID swap, dup presença(=0), recuperação oclusão, latência, filas, CPU, memória.
