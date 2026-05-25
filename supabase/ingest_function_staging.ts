// Edge Function para Supabase Staging
// Recebe eventos do edge device e insere nas tabelas
// Nome sugerido: ingest-events

import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type, x-device-token',
}

serve(async (req) => {
  // Handle CORS preflight
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders })
  }

  try {
    // Verificar autenticação
    // IMPORTANTE: Usar query parameter para evitar validação JWT automática do Supabase
    // O Supabase valida Authorization header ANTES da function executar
    const url = new URL(req.url)
    const token = url.searchParams.get('token')
    
    if (!token) {
      return new Response(
        JSON.stringify({ error: 'Unauthorized: Missing device token. Use ?token= query parameter' }),
        { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      )
    }
    
    // Validar token (comparar com variável de ambiente)
    // Aceita diferentes nomes de variáveis
    const deviceTokensEnv = Deno.env.get('EDGE_DEVICE_TOKENS') ?? 
                           Deno.env.get('TOKENS_DE_DISPOSITIVO_DE_BORDA') ?? ''
    const validTokens = deviceTokensEnv.split(',').map(t => t.trim()).filter(t => t.length > 0)
    
    if (validTokens.length === 0) {
      console.warn('No EDGE_DEVICE_TOKENS configured - allowing all requests (INSECURE!)')
    } else if (!validTokens.includes(token)) {
      return new Response(
        JSON.stringify({ error: 'Unauthorized: Invalid device token' }),
        { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      )
    }

    // Parse do payload
    const payload = await req.json()
    const { event_type, event_id } = payload

    if (!event_type || !event_id) {
      return new Response(
        JSON.stringify({ error: 'Missing required fields: event_type and event_id' }),
        { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      )
    }

    // Criar cliente Supabase
    // Tenta diferentes nomes de variáveis (Supabase pode ter nomes diferentes)
    const supabaseUrl = Deno.env.get('SUPABASE_URL') ?? 
                       Deno.env.get('URL_SUPABASE') ?? 
                       Deno.env.get('URL_DO_BANCO_DE_DADOS_SUPABASE') ?? ''
    
    const serviceRoleKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
    
    if (!supabaseUrl || !serviceRoleKey) {
      return new Response(
        JSON.stringify({ error: 'Server configuration error: Missing SUPABASE_URL or SERVICE_ROLE_KEY' }),
        { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      )
    }
    
    const supabaseClient = createClient(supabaseUrl, serviceRoleKey)

    // Verificar idempotência (usar função helper ou query direta)
    const { data: existing } = await supabaseClient
      .from('edge_events_raw')
      .select('event_id')
      .eq('event_id', event_id)
      .limit(1)
      .single()

    if (existing) {
      return new Response(
        JSON.stringify({ 
          ok: true, 
          received: 1, 
          inserted: 0, 
          duplicated: 1,
          message: 'Event already processed'
        }),
        { status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      )
    }

    // Extrair campos comuns
    const device_id = payload.device_id || 'unknown'
    const school_id = payload.school_id || 'unknown'
    const room_id = payload.room_id || null
    const ts = payload.timestamp || payload.ts_start || Math.floor(Date.now() / 1000)

    // Inserir em edge_events_raw (idempotente via UNIQUE constraint)
    const { error: rawError } = await supabaseClient
      .from('edge_events_raw')
      .insert({
        event_id: event_id,
        event_type: event_type,
        device_id: device_id,
        school_id: school_id,
        room_id: room_id,
        payload: payload,
        ts: ts
      })

    if (rawError) {
      // Se erro for de duplicação, considerar sucesso (idempotência)
      if (rawError.code === '23505') {  // unique_violation
        return new Response(
          JSON.stringify({ 
            ok: true, 
            received: 1, 
            inserted: 0, 
            duplicated: 1 
          }),
          { status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
        )
      }
      throw rawError
    }

    // Inserir em tabela normalizada baseado no event_type
    let normalizedInserted = 0
    let normalizedError = null

    if (event_type === 'attendance_checkin') {
      const { error } = await supabaseClient
        .from('attendance_checkins')
        .insert({
          event_id: event_id,
          student_id: payload.student_id,
          school_id: school_id,
          room_id: room_id,
          device_id: device_id,
          timestamp: payload.timestamp,
          confidence: payload.confidence,
          model_version: payload.model_version,
          template_version: payload.template_version,
          face_quality: payload.face_quality
        })
        .select()
      
      if (!error) {
        normalizedInserted = 1
      } else if (error.code !== '23505') {  // Ignorar duplicação
        normalizedError = error
      }
    } else if (event_type === 'engagement_window') {
      const { error } = await supabaseClient
        .from('engagement_windows')
        .insert({
          event_id: event_id,
          school_id: school_id,
          room_id: room_id,
          device_id: device_id,
          ts_start: payload.ts_start,
          ts_end: payload.ts_end,
          faces_detected_avg: payload.faces_detected_avg,
          engagement_index_avg: payload.engagement_index_avg,
          states_distribution: payload.states_distribution,
          model_version: payload.model_version
        })
        .select()
      
      if (!error) {
        normalizedInserted = 1
      } else if (error.code !== '23505') {  // Ignorar duplicação
        normalizedError = error
      }
    }

    if (normalizedError) {
      console.error('Normalized insert error:', normalizedError)
      // Não falhar o request se raw insert funcionou
    }

    return new Response(
      JSON.stringify({ 
        ok: true, 
        received: 1, 
        inserted: 1, 
        duplicated: 0,
        normalized_inserted: normalizedInserted
      }),
      { status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    )

  } catch (error) {
    console.error('Ingest error:', error)
    return new Response(
      JSON.stringify({ error: error.message || 'Internal server error' }),
      { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    )
  }
})
