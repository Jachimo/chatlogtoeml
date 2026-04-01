<?xml version="1.0"?>

<!-- this xslt is from http://trac.adium.im/ticket/6569 -->

<!--
	Adium is the legal property of its developers, whose names are listed in the copyright file included
	with this source distribution.

	This program is free software; you can redistribute it and/or modify it under the terms of the GNU
	General Public License as published by the Free Software Foundation; either version 2 of the License,
	or (at your option) any later version.

	This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even
	the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
	Public License for more details.

	You should have received a copy of the GNU General Public License along with this program; if not,
	write to the Free Software Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.

	Purpose:
		Format an Adium log file as XHTML

	Parameters:
		title   A string to use for the page title
-->

<xsl:stylesheet version="1.0"
	xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
	xmlns:adium="http://purl.org/net/ulf/ns/0.4-02"
	xmlns="http://www.w3.org/1999/xhtml"
	exclude-result-prefixes="adium">

	<xsl:output method="xml"
		doctype-public="-//W3C//DTD XHTML 1.0 Strict//EN"
		doctype-system="http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd"
		indent="yes" encoding="utf-8"/>
		
	<xsl:strip-space elements="*"/>

	<xsl:param name="title" select="'Chat'"/>

	<!-- Process chats -->
	<xsl:template match="adium:chat">
		<html>
			<head>
				<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
				<title><xsl:value-of select="$title"/></title>
				<link rel="stylesheet" href="http://paulirish.com/adiumlogs.css"/>

			</head>
			<body>
				<xsl:apply-templates/>
			</body>
		</html>
	</xsl:template>

	<!-- Process events -->
	<xsl:template match="adium:event">
		<div class="event">
			<xsl:value-of select="@type"/>
			<xsl:text>: </xsl:text>
			<xsl:value-of select="translate(@time, 'T', ' ')"/>
		</div>
	</xsl:template>

	<!-- Process messages -->
	<xsl:template match="adium:message">
		<!-- Record whether this is a follow-on message -->
		<xsl:variable name="prec" select="preceding-sibling::*[1]"/>
		<xsl:variable name="follow-on">
			<xsl:if test="$prec[self::adium:message] and $prec/@sender = @sender">
				<xsl:text>follow-on</xsl:text>
			</xsl:if>
		</xsl:variable>
		<!-- Record whether this is from the principal account -->
		<xsl:variable name="principal">
			<xsl:if test="@sender = /adium:chat/@account">
				<xsl:text>principal</xsl:text>
			</xsl:if>
		</xsl:variable>
		
		<!-- Record if this is an auto message  -->
		<xsl:variable name="auto">
			<xsl:if test="@auto = 'true'">
				<xsl:text>auto</xsl:text>
			</xsl:if>
		</xsl:variable>
		
		<!-- Create message div -->
		<div class="message {$principal} {$follow-on} {$auto}">
			<!-- Include a sender box when this is not a follow-on message -->
			<xsl:if test="$follow-on = ''">
				<div class="sender">
					<xsl:apply-templates select="@sender|@alias"/>
				</div>
			</xsl:if>
			<!-- Process attributes -->
			<div class="meta">
				<xsl:apply-templates select="@*[not(name() = 'sender' or name() = 'alias')]"/>
			</div>
			<div class="content">
				<!-- Process child elements etc. -->
				<xsl:apply-templates select="node()"/>
			</div>
		</div>
	</xsl:template>

	<xsl:template match="@sender|@alias">
		<xsl:if test="name() = 'alias' or not(../@alias)">
			<span class="sender">
				<xsl:value-of select="."/>
			</span>
		</xsl:if>
	</xsl:template>


	<xsl:template match="@auto">
		<span class="auto">
			<xsl:value-of select="."/>
		</span>
	</xsl:template>
	
	<xsl:template match="@time">
		<span class="time">
			<xsl:value-of select="substring(., 12, 8)"/>
		</span>
	</xsl:template>

	<xsl:template match="adium:message/@*" priority="0">
		<xsl:message>Unhandled attribute: message/@<xsl:value-of select="name()"/>&#10;</xsl:message>
	</xsl:template>

	<!-- Copy elements but strip off the namespace -->
	<xsl:template match="*">
		<xsl:element name="{local-name()}">
			<xsl:apply-templates select="node()|@*"/>
		</xsl:element>
	</xsl:template>

	<!-- Copy atrributes but strip off the namespace -->
	<xsl:template match="@*">
		<xsl:attribute name="{local-name()}">
			<xsl:apply-templates/>
		</xsl:attribute>
	</xsl:template>

</xsl:stylesheet>
