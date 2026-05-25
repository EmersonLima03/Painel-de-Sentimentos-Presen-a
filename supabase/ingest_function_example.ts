// Exemplo de Edge Function para Supabase
// Recebe eventos do edge device e insere nas tabelas

import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2'

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
}

serve(async (req) => {
  // Handle CORS preflight
  if (req.method === 'OPTIONS') {
    return new Response('ok', { headers: corsHeaders })
  }

  try {
    // Verificar autenticação
    const authHeader = req.headers.get('Authorization')
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      return new Response(
        JSON.stringify({ error: 'Unauthorized' }),
        { status: 401, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      )
    }

    const token = authHeader.replace('Bearer ', '')
    // Aqui você validaria o token do dispositivo
    // Por exemplo, comparando com uma tabela de device_tokens

    // Parse do payload
    const payload = await req.json()
    const { event_type, event_id } = payload

    if (!event_type || !event_id) {
      return new Response(
        JSON.stringify({ error: 'Missing event_type or event_id' }),
        { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      )
    }

    // Criar cliente Supabase
    const supabaseClient = createClient(
      Deno.env.get('SUPABASE_URL') ?? '',
      Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? ''
    )

    // Verificar idempotência
    let exists = false
    if (event_type === 'attendance_checkin') {
      const { data } = await supabaseClient
        .from('attendance_events_raw')
        .select('event_id')
        .eq('event_id', event_id)
        .limit(1)
      
      exists = (data && data.length > 0)
    } else if (event_type === 'engagement_window') {
      const { data } = await supabaseClient
        .from('engagement_windows')
        .select('event_id')
        .eq('event_id', event_id)
        .limit(1)
      
      exists = (data && data.length > 0)
    }

    if (exists) {
      return new Response(
        JSON.stringify({ message: 'Event already processed', event_id }),
        { status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      )
    }

    // Inserir evento
    if (event_type === 'attendance_checkin') {
      const { error } = await supabaseClient
        .from('attendance_events_raw')
        .insert({
          event_id: payload.event_id,
          student_id: payload.student_id,
          school_id: payload.school_id,
          room_id: payload.room_id,
          device_id: payload.device_id,
          timestamp: payload.timestamp,
          confidence: payload.confidence,
          model_version: payload.model_version,
          template_version: payload.template_version,
          face_quality: payload.face_quality
        })

      if (error) {
        throw error
      }
    } else if (event_type === 'engagement_window') {
      const { error } = await supabaseClient
        .from('engagement_windows')
        .insert({
          event_id: payload.event_id,
          school_id: payload.school_id,
          room_id: payload.room_id,
          device_id: payload.device_id,
          ts_start: payload.ts_start,
          ts_end: payload.ts_end,
          faces_detected_avg: payload.faces_detected_avg,
          engagement_index_avg: payload.engagement_index_avg,
          states_distribution: payload.states_distribution,
          model_version: payload.model_version
        })

      if (error) {
        throw error
      }
    } else {
      return new Response(
        JSON.stringify({ error: 'Unknown event_type' }),
        { status: 400, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
      )
    }

    return new Response(
      JSON.stringify({ message: 'Event processed', event_id }),
      { status: 200, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    )

  } catch (error) {
    return new Response(
      JSON.stringify({ error: error.message }),
      { status: 500, headers: { ...corsHeaders, 'Content-Type': 'application/json' } }
    )
  }
})
